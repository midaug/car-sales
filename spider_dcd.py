# -*- coding: UTF8 -*-
import base64
import json
import os
import sys
import time
import warnings
from datetime import datetime

import requests
from dateutil.relativedelta import relativedelta
from requests.packages import urllib3

urllib3.disable_warnings()
warnings.filterwarnings("ignore")

# 数据保存目录
data_path = './data'


def b64Decode(value):
    """base64 解码，源码里的接口地址都是编码后的，运行时再还原"""
    return base64.b64decode(value.encode('utf8')).decode('utf8')


# 站点和接口路径做了 base64 编码，避免仓库被扫描工具/搜索引擎直接匹配到域名
# 需要改动时按下面的方式重新生成：
#   python3 -c "import base64;print(base64.b64encode('https://www.example.com'.encode()).decode())"
site_url = b64Decode('aHR0cHM6Ly93d3cuZG9uZ2NoZWRpLmNvbQ==')
api_path = b64Decode('L21vdG9yL3BjL2Nhci9yYW5rX2RhdGE=')

# 也可以用环境变量 DCD_BASE_URL 覆盖站点域名（例如在 GitHub Secrets 里配置）
env_base_url = (os.environ.get('DCD_BASE_URL') or '').strip()
if env_base_url:
    site_url = env_base_url
site_url = site_url.rstrip('/')
api_url = site_url + api_path

# 接口请求头，带上 UA / Referer 降低被风控的概率
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': '{0}/motor/rank/'.format(site_url),
    'Accept': 'application/json, text/plain, */*',
}

request_timeout = 30
max_retry = 3
# 接口单页最多返回 100 条，按 offset 翻页
page_size = 100
# 翻页上限，防止接口异常时死循环（100 页 = 1 万条）
max_offset = page_size * 100

# 能源类型：接口用 new_energy_type 区分，1=纯电 2=插混 3=增程
# 4 是「同车系同时有纯电和增程版本」（双动力），2025 年后车型越来越多，需要一并收取
energy_types = {'1': 1, '2': 2, '3': 3, '4': 4}
energy_url = api_url + ('?aid=1839&app_name=auto_web_pc&city_name=&count={count}&offset={offset}'
                        '&month={month}&new_energy_type={net}&rank_data_type=11&brand_id=&price='
                        '&manufacturer=&outter_detail_type=&nation=0')


def replaceStr(s=''):
    return s.replace(' ', '').replace(',', '')


# 只保留页面用得到的字段。jsDelivr 对单仓库有 50MB 上限，全字段存会超标
keep_fields = ('series_id', 'series_name', 'image', 'count', 'price',
               'last_rank', 'rank', 'brand_name', 'sub_brand_name', 'outter_detail_type')


def slimCar(car):
    """裁掉用不到的字段，图片地址只留基础部分（尺寸参数由页面拼）"""
    out = {}
    for field in keep_fields:
        if field in car:
            out[field] = car[field]
    image = out.get('image')
    if image and '~tplv-' in image:
        out['image'] = image.split('~tplv-')[0]
    return out


def maskUrl(url):
    """日志里隐去域名，仓库的 Actions 日志是公开的"""
    if site_url and url and site_url in url:
        return url.replace(site_url, '***')
    return url


def mkdir(path):
    path = path.strip()
    path = path.rstrip('\\')
    isExists = os.path.exists(path)
    if not isExists:
        os.makedirs(path)
        return True
    else:
        return False


def wFile(str, path):
    open(path, 'w').close()
    file = open(path, 'w', encoding="utf8")
    file.write(str)
    file.close()


def rFile(path):
    """读取文件内容，文件不存在或读取失败返回 None"""
    try:
        f = open(path, 'r', encoding="utf8")
        dataStr = f.read()
        f.close()
        return dataStr
    except Exception:
        return None


def requestPage(url, dateStr):
    """请求一页数据，失败会重试，最终失败返回 None"""
    for attempt in range(1, max_retry + 1):
        try:
            response = requests.get(url=url, headers=headers, verify=False, timeout=request_timeout)
            response = response.json()
            if 0 != response.get('status'):
                raise ValueError('接口返回 status={0}, message={1}'.format(response.get('status'), response.get('message')))
            return response['data']['list'] or []
        except Exception as e:
            # 只打印一行错误，避免日志被 traceback 淹没
            print('warn request failed ({0}/{1}) month={2} , {3}: {4}'.format(
                attempt, max_retry, dateStr, type(e).__name__, str(e).replace('\n', ' ')[:200]))
            if attempt < max_retry:
                time.sleep(attempt * 3)
    print('ERROR 请求失败 month={0} , url={1}'.format(dateStr, maskUrl(url)))
    return None


def jsWrap(key, dataStr):
    """包装成一行 js，页面用 <script> 直接加载写进 sessionStorage"""
    return "window.sessionStorage.setItem('{0}', '{1}')".format(key, dataStr)


# 需要强制重抓的月份（封面数据可能被写错过），用环境变量指定：FORCE_MONTHS=202502,202503
force_months = set(x.strip() for x in (os.environ.get('FORCE_MONTHS') or '').split(',') if x.strip())


def readJs(path, key):
    """把 .js 里的 JSON 还原成对象，读不出来返回 None"""
    s = rFile(path)
    if not s:
        return None
    prefix = "window.sessionStorage.setItem('{0}', '".format(key)
    if not s.startswith(prefix) or not s.endswith("')"):
        return None
    try:
        return json.loads(s[len(prefix):-2])
    except Exception:
        return None


def dataSig(data):
    """月度数据的指纹：只取 (series_id, count)，用来判断两个月是不是同一份数据"""
    if not isinstance(data, dict):
        return None
    pairs = []
    for k, v in data.items():
        if k == 'order' or not isinstance(v, dict):
            continue
        pairs.append((str(v.get('series_id')), v.get('count')))
    return tuple(sorted(pairs))


def neighborSig(dir, dateStr, car_type, step):
    """读取相邻月份（step=-1 上个月，step=+1 下个月）已存数据的指纹，没有则返回 None"""
    try:
        y, m = int(dateStr[:4]), int(dateStr[4:])
        m += step
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        ym = '{0:04d}{1:02d}'.format(y, m)
        p = '{0}/{1}/{2}/{3}.js'.format(data_path, y, '{0:02d}'.format(m), car_type)
        if not os.path.exists(p):
            return None
        d = readJs(p, '{0}_{1}'.format(car_type, ym))
        return dataSig(d)
    except Exception:
        return None


_latest_month = []
_latest_sig = {}


def latestMonth():
    """数据目录里最新的一个月（源站把历史月回退时，返回的就是这个月的数据）"""
    if not _latest_month:
        best = None
        for year in sorted(os.listdir(data_path)):
            yp = os.path.join(data_path, year)
            if not os.path.isdir(yp) or not year.isdigit():
                continue
            for m in sorted(os.listdir(yp)):
                if os.path.isdir(os.path.join(yp, m)) and os.path.exists(os.path.join(yp, m, 'car_all.js')):
                    ym = year + m
                    if best is None or ym > best:
                        best = ym
        _latest_month.append(best)
    return _latest_month[0]


def latestSig(dateStr, car_type):
    """最新月份已存数据的指纹；dateStr 本身就是最新月时返回 None"""
    ym = latestMonth()
    if not ym or ym == dateStr:
        return None
    if car_type not in _latest_sig:
        p = '{0}/{1}/{2}/{3}.js'.format(data_path, ym[:4], ym[4:], car_type)
        _latest_sig[car_type] = dataSig(readJs(p, '{0}_{1}'.format(car_type, ym))) if os.path.exists(p) else None
    return _latest_sig[car_type]


def requestCarData(url, jsPath, dir, dateStr, car_type):
    """下载一个月的数据（接口单页最多 100 条，需要按 offset 翻页）。
    只保留页面用得到的字段，仓库体积能小一半多。
    返回 (dataStr, created, status)，status 为 ok / stale / fail：
      stale = 源站把这个月回退成了最新月的数据（和相邻月完全一致），不能写入"""
    key = '{0}_{1}'.format(car_type, dateStr)
    # 当文件存在时直接读取，避免重复下载
    if os.path.exists(jsPath):
        data = readJs(jsPath, key)
        if data is not None:
            print('info dataPath exists: {0}'.format(jsPath))
            return json.dumps(data, ensure_ascii=False), False, 'ok'
        print('warn unreadable data file, re-download: {0}'.format(jsPath))

    order = []
    data = {}
    offset = 0
    while offset <= max_offset:
        carList = requestPage(url.format(month=dateStr, offset=offset, count=page_size), dateStr)
        if carList is None:
            # 翻页中途失败就整月放弃，避免保存残缺数据
            return None, False, 'fail'
        for carSales in carList:
            item = slimCar(carSales)
            if 'series_id' not in item:
                continue
            car_key = '{0}_{1}'.format('car', item['series_id'])
            if car_key not in data:
                order.append(car_key)
            data[car_key] = item
        print('request month={0} , offset={1} , list.len={2}'.format(dateStr, offset, len(carList)))
        if len(carList) < page_size:
            break
        offset += page_size

    if not order:
        print('warn month={0} 没有返回任何数据'.format(dateStr))

    # 源站对太早的月份会直接回退成「最新月」的数据（内容与最新月或相邻月一模一样）。
    # 这种数据写进去会污染历史，直接丢弃并让调用方跳过该月。
    sig = dataSig(data)
    refs = [
        (neighborSig(dir, dateStr, car_type, -1), '上个月'),
        (neighborSig(dir, dateStr, car_type, 1), '下个月'),
        (latestSig(dateStr, car_type), '最新月份'),
    ]
    for rsig, name in refs:
        if sig is not None and rsig is not None and sig == rsig:
            print('ERROR month={0} 返回内容与{1}完全相同，判定为源站回退到最新月，已跳过'.format(dateStr, name))
            return None, False, 'stale'

    data['order'] = order
    dataStr = json.dumps(data, ensure_ascii=False)
    mkdir(dir)
    wFile(jsWrap(key, dataStr), jsPath)
    print('info month={0} 共 {1} 条'.format(dateStr, len(order)))
    return dataStr, True, 'ok'


def start(url, dateStr, car_type):
    """抓取一月一类数据，返回 ok / stale / fail"""
    fileDir = '{dir}/{year}/{month}'.format(dir=data_path, year=dateStr[:4], month=dateStr[4:6])
    jsPath = '{dir}/{type}.js'.format(dir=fileDir, type=car_type)
    if dateStr in force_months and os.path.exists(jsPath):
        os.remove(jsPath)
        print('info force re-download: {0}'.format(jsPath))
    carData, created, status = requestCarData(url, jsPath, fileDir, dateStr, car_type)
    return status


def neighborEnergy(dir, dateStr, step):
    """读取相邻月份的能源映射，没有则返回 None"""
    try:
        y, m = int(dateStr[:4]), int(dateStr[4:])
        m += step
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        ym = '{0:04d}{1:02d}'.format(y, m)
        p = '{0}/{1}/{2}/energy.js'.format(data_path, y, '{0:02d}'.format(m))
        if not os.path.exists(p):
            return None
        d = readJs(p, 'energy_{0}'.format(ym))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def requestEnergyMap(dateStr, dir):
    """抓取一个月的能源类型映射 {series_id: 1|2|3|4}，纯电/插混/增程/双动力分开取。
    只存 id 和类型，一个月大约 4KB。返回 (data, created, status)"""
    jsPath = '{dir}/energy.js'.format(dir=dir)
    key = 'energy_{0}'.format(dateStr)
    if os.path.exists(jsPath):
        cached = readJs(jsPath, key)
        if isinstance(cached, dict):
            print('info dataPath exists: {0}'.format(jsPath))
            return cached, False, 'ok'
        print('warn unreadable data file, re-download: {0}'.format(jsPath))

    result = {}
    for net, net_value in energy_types.items():
        offset = 0
        while offset <= max_offset:
            carList = requestPage(energy_url.format(month=dateStr, offset=offset, count=page_size, net=net), dateStr)
            if carList is None:
                # 中途失败整月放弃，避免存半份映射
                return None, False, 'fail'
            for car in carList:
                series_id = car.get('series_id')
                if series_id is not None:
                    result[str(series_id)] = net_value
            if len(carList) < page_size:
                break
            offset += page_size

    # 能源映射只记「车系 -> 类型」，车系集合本身很稳定，相邻月完全一致是正常现象，
    # 用相邻月比对会误杀（2025-07 就踩过）。这里改成看「当月新能源榜的覆盖率」：
    # 源站回退成最新月快照时，当月榜单里大量车系在映射里查不到，覆盖率会明显偏低。
    coverage = None
    nePath = '{0}/{1}/{2}/car_new_energy.js'.format(data_path, dateStr[:4], dateStr[4:])
    ne = readJs(nePath, 'car_new_energy_{0}'.format(dateStr))
    if isinstance(ne, dict) and ne.get('order'):
        hit = 0
        for k in ne['order']:
            it = ne.get(k)
            if isinstance(it, dict) and str(it.get('series_id')) in result:
                hit += 1
        coverage = hit / len(ne['order'])
    if not result or (coverage is not None and coverage < 0.6):
        print('ERROR energy month={0} 覆盖率过低({1})，判定为快照回退，已跳过'.format(dateStr, coverage))
        return None, False, 'stale'

    mkdir(dir)
    print('info energy month={0} 共 {1} 条'.format(dateStr, len(result)))
    return result, True, 'ok'


def startEnergy(dateStr):
    """抓取一个月的能源类型映射，返回 ok / stale / fail"""
    fileDir = '{dir}/{year}/{month}'.format(dir=data_path, year=dateStr[:4], month=dateStr[4:6])
    jsPath = '{0}/energy.js'.format(fileDir)
    if dateStr in force_months and os.path.exists(jsPath):
        os.remove(jsPath)
        print('info force re-download: {0}'.format(jsPath))
    result, created, status = requestEnergyMap(dateStr, fileDir)
    if status != 'ok':
        return status
    if created:
        dataStr = json.dumps(result, ensure_ascii=False, sort_keys=True)
        wFile(jsWrap('energy_{0}'.format(dateStr), dataStr), jsPath)
    return 'ok'


def ymShift(ym, step):
    """月份加减，返回 YYYYMM"""
    y, m = int(ym[:4]), int(ym[4:])
    m += step
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return '{0:04d}{1:02d}'.format(y, m)


def monthExists(ym):
    return os.path.exists('{0}/{1}/{2}/car_all.js'.format(data_path, ym[:4], ym[4:]))


def fillMissing(start, end):
    """补缺月：源站彻底没有的月份（例如 2020-02），按「宁可重复也不能缺一个月」的口径，
    用最近的相邻月复制一份并打上 _est 标记，页面会标明「估算」，时间轴不断档。
    只兜底「源站本来就不给」的老月份（24 个月以前）；最近两年的月份抓不到就当失败，
    不拿相邻月顶替，免得一次网络抖动被悄悄糊过去。"""
    filled = []
    # 源站最近两年都能正常返回，这个范围内的缺月一律视为抓取失败，交给重试和 Actions 报红
    young = ymShift(end, -24)
    month = start
    while month <= end:
        if not monthExists(month):
            if month > young:
                print('warn month={0} 缺数据但月份太新，不做兜底，等下次重试'.format(month))
                month = ymShift(month, 1)
                continue
            src = None
            for step in (-1, 1, -2, 2, -3, 3):
                cand = ymShift(month, step)
                if monthExists(cand):
                    src = cand
                    break
            if src:
                for t in ('car_all', 'car_new_energy', 'energy'):
                    sp = '{0}/{1}/{2}/{3}.js'.format(data_path, src[:4], src[4:], t)
                    dp = '{0}/{1}/{2}/{3}.js'.format(data_path, month[:4], month[4:], t)
                    obj = readJs(sp, '{0}_{1}'.format(t, src))
                    if not isinstance(obj, dict):
                        continue
                    if t != 'energy':
                        obj = dict(obj)
                        obj['_est'] = src
                    mkdir(os.path.dirname(dp))
                    wFile(jsWrap('{0}_{1}'.format(t, month),
                                 json.dumps(obj, ensure_ascii=False, sort_keys=(t == 'energy'))), dp)
                filled.append('{0}<-{1}'.format(month, src))
                print('warn month={0} 源站无当月数据，已用 {1} 兜底填充（页面会标注估算）'.format(month, src))
        month = ymShift(month, 1)
    return filled


def mergeYear(car_type):
    """按年合并，内容和现有文件一致时不重写，避免产生无意义的 git 变更"""
    years = sorted([f for f in os.listdir(data_path) if os.path.isdir(data_path + '/' + f)])
    for year in years:
        year_path = data_path + "/" + year
        allCarJsPath = '{dir}/year_merge-{type}.js'.format(dir=year_path, type=car_type)
        dataMap = {}
        months = sorted([year_path + '/' + f for f in os.listdir(year_path) if os.path.isdir(year_path + '/' + f)])
        for month in months:
            dateStr = year + os.path.basename(month)
            filePath = '{dir}/{type}.js'.format(dir=month, type=car_type)
            cars = readJs(filePath, '{0}_{1}'.format(car_type, dateStr))
            if not cars:
                continue
            for key in cars:
                if 'order' == key or key.startswith('_'):
                    continue
                if key in dataMap:
                    oldCount = dataMap[key].get('count') or 0
                    newCount = cars[key].get('count') or 0
                    dataMap[key]['count'] = int(oldCount) + int(newCount)
                else:
                    dataMap[key] = cars[key]
        dataMap['order'] = [key for key in dataMap]
        dataStr = json.dumps(dataMap, ensure_ascii=False)
        mkdir(year_path)
        jsStr = jsWrap('year_merge-{0}_{1}'.format(car_type, year), dataStr)
        if rFile(allCarJsPath) != jsStr:
            wFile(jsStr, allCarJsPath)
            print('info mergeYear updated: {0}'.format(allCarJsPath))


def mergeYearEnergy():
    """把每月 energy.js 合并成年度映射，内容没变不重写"""
    years = sorted([f for f in os.listdir(data_path) if os.path.isdir(data_path + '/' + f)])
    for year in years:
        year_path = data_path + "/" + year
        jsPath = '{0}/year_merge-energy.js'.format(year_path)
        merged = {}
        months = sorted([year_path + '/' + f for f in os.listdir(year_path) if os.path.isdir(year_path + '/' + f)])
        for month in months:
            dateStr = year + os.path.basename(month)
            monthMap = readJs('{0}/energy.js'.format(month), 'energy_{0}'.format(dateStr))
            if isinstance(monthMap, dict):
                merged.update(monthMap)
        if not merged:
            continue
        dataStr = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        mkdir(year_path)
        jsStr = jsWrap('year_merge-energy_{0}'.format(year), dataStr)
        if rFile(jsPath) != jsStr:
            wFile(jsStr, jsPath)
            print('info mergeYearEnergy updated: {0}'.format(jsPath))


def writeLastDate():
    """把最新一个有数据的月份写入 last_date.js（页面默认选中的月份）"""
    last = None
    for year in sorted(os.listdir(data_path)):
        year_path = '{0}/{1}'.format(data_path, year)
        if not os.path.isdir(year_path):
            continue
        for m in sorted(os.listdir(year_path)):
            month_path = '{0}/{1}'.format(year_path, m)
            if not os.path.isdir(month_path):
                continue
            if os.path.exists('{0}/car_all.js'.format(month_path)):
                ym = '{0}{1}'.format(year, m)
                if last is None or ym > last:
                    last = ym
    if last:
        wFile("window.sessionStorage.setItem('last_date','{0}')".format(last), data_path + "/last_date.js")
        print('info last_date={0}'.format(last))


if __name__ == "__main__":
    # 全部车型url（{month} 月份，{offset} 翻页偏移）
    car_all_url = api_url + '?aid=1839&app_name=auto_web_pc&city_name=&count={count}&offset={offset}&month={month}&new_energy_type=&rank_data_type=11&brand_id=&price=&manufacturer=&outter_detail_type=&nation=0'
    # 新能源销量url
    car_new_energy_url = api_url + '?aid=1839&app_name=auto_web_pc&city_name=&count={count}&offset={offset}&month={month}&new_energy_type=1%2C2%2C3%2C4&rank_data_type=11&brand_id=&price=&manufacturer=&outter_detail_type=&nation=0'
    # 开始时间
    start_month = os.environ.get('START_MONTH', '202002')
    # 时间格式化
    format_str = '%Y%m'
    # 截至时间，默认为上个月
    end_month = datetime.strftime(datetime.now() - relativedelta(months=1), format_str)
    # 创建数据存储目录
    mkdir(data_path)
    print('info api={0} , range={1} ~ {2}'.format(maskUrl(api_url), start_month, end_month))

    total = 0
    success = 0
    failed = []
    skipped = []
    month = start_month
    try:
        while month <= end_month:
            for url, car_type in ((car_all_url, 'car_all'), (car_new_energy_url, 'car_new_energy')):
                total += 1
                status = start(url, month, car_type)
                if status == 'ok':
                    success += 1
                elif status == 'stale':
                    skipped.append('{0}/{1}'.format(car_type, month))
                else:
                    failed.append('{0}/{1}'.format(car_type, month))
            # 能源类型映射（纯电/插混/增程），只存 series_id -> 类型，体积很小
            total += 1
            status = startEnergy(month)
            if status == 'ok':
                success += 1
            elif status == 'stale':
                skipped.append('energy/{0}'.format(month))
            else:
                failed.append('energy/{0}'.format(month))
            month = datetime.strftime(datetime.strptime(month, format_str) + relativedelta(months=1), format_str)
        # 源站确实没有的月份用相邻月兜底，保证时间轴不断档（页面会标注「估算」）
        last = latestMonth() or end_month
        filled = fillMissing(start_month, last)
        mergeYear('car_all')
        mergeYear('car_new_energy')
        mergeYearEnergy()
        writeLastDate()
        print('Finished, {0}/{1} success'.format(success, total))
        if skipped:
            print('Skipped (源站已不提供该月，返回的是最新月数据): {0}'.format(', '.join(skipped)))
        if filled:
            print('Filled (源站无数据，用相邻月兜底): {0}'.format(', '.join(filled)))
    except Exception:
        import traceback
        traceback.print_exc()
        print('error')
        sys.exit(1)

    # 有失败就以非 0 退出，让 GitHub Actions 直接变成红色，方便发现问题
    if failed:
        print('Failed months: {0}'.format(', '.join(failed)))
        sys.exit(1)
