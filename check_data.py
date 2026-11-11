# -*- coding: UTF8 -*-
"""数据体检：扫一遍 data/ 下的月度文件，找出「内容重复」「缺失」「读不出来」的月份。

源站对太早的月份会静默回退成最新月的数据，写进去就会让几个月甚至几年变成同一份数据。
这个脚本用内容指纹把它们揪出来，跑完有异常会以非 0 退出：

    python3 check_data.py            # 全量体检
    python3 check_data.py 2020 2021  # 只看指定年份
"""
import json
import os
import sys
from collections import defaultdict

data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def read_js(path, key):
    """把 .js 里的 JSON 还原成对象，格式不对返回 None"""
    try:
        s = open(path, encoding='utf8').read()
    except Exception:
        return None
    pre = "window.sessionStorage.setItem('{0}', '".format(key)
    if not s.startswith(pre) or not s.endswith("')"):
        return None
    try:
        return json.loads(s[len(pre):-2])
    except Exception:
        return None


def months_of(year_filter):
    out = []
    for year in sorted(os.listdir(data_path)):
        yp = os.path.join(data_path, year)
        if not os.path.isdir(yp) or not year.isdigit():
            continue
        if year_filter and year not in year_filter:
            continue
        for m in sorted(os.listdir(yp)):
            mp = os.path.join(yp, m)
            if os.path.isdir(mp) and os.path.exists(os.path.join(mp, 'car_all.js')):
                out.append(year + m)
    return out


def same_range(a, b):
    """a 到 b 之间每个自然月，用来找缺月"""
    y, m = int(a[:4]), int(a[4:])
    out = []
    while True:
        cur = '{0:04d}{1:02d}'.format(y, m)
        if cur > b:
            break
        out.append(cur)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def main():
    years = set(sys.argv[1:])
    months = months_of(years)
    if not months:
        print('没有找到任何数据')
        return 1

    rows = []
    broken = []
    for ym in months:
        p = os.path.join(data_path, ym[:4], ym[4:], 'car_all.js')
        d = read_js(p, 'car_all_' + ym)
        if not isinstance(d, dict):
            broken.append(ym)
            continue
        # _est 是补缺月时写进去的标记（值 = 被复制的月份），不是车型
        items = [v for k, v in d.items() if k != 'order' and not k.startswith('_')]
        if not items:
            broken.append(ym)
            continue
        top = max(items, key=lambda x: x.get('count') or 0)
        sig = tuple(sorted((str(v.get('series_id')), v.get('count')) for v in items))
        rows.append((ym, len(items), sum(v.get('count') or 0 for v in items), top, sig, d.get('_est')))

    print('{0:<8}{1:>6}{2:>13}  冠军'.format('月份', '车系', '总销量'))
    for ym, n, s, top, _, est in rows:
        print('{0:<8}{1:>6}{2:>13,}  {3} {4:,}{5}'.format(
            ym, n, s, top.get('series_name'), top.get('count') or 0,
            '   [估算：沿用 {0}]'.format(est) if est else ''))

    by_sig = defaultdict(list)
    for ym, _, _, _, sig, est in rows:
        if not est:
            by_sig[sig].append(ym)

    dup = {sig: v for sig, v in by_sig.items() if len(v) > 1}
    missing = [ym for ym in same_range(rows[0][0], rows[-1][0]) if ym not in {r[0] for r in rows}]
    estimated = [(r[0], r[5]) for r in rows if r[5]]

    years_sum = defaultdict(lambda: [0, 0])
    for ym, n, s, _, _, _ in rows:
        years_sum[ym[:4]][0] += n
        years_sum[ym[:4]][1] += s
    print('\n年度合计')
    for y in sorted(years_sum):
        n, s = years_sum[y]
        print('  {0}: {1:>6} 款次  {2:>13,}'.format(y, n, s))

    if estimated:
        print('\n估算月份（源站无当月数据，用相邻月复制，页面会标注）: {0}'.format(
            ', '.join('{0}<-{1}'.format(a, b) for a, b in estimated)))
    if missing:
        print('\n缺失月份（源站不提供）: {0}'.format(', '.join(missing)))
    if broken:
        print('\n读不出来/空文件: {0}'.format(', '.join(broken)))
    if dup:
        print('\n内容完全相同的月份（说明被最新月数据覆盖过）:')
        for v in dup.values():
            print('  {0}  {1} 个月'.format(', '.join(v), len(v)))

    ok = not broken and not dup and not missing
    print('\n共 {0} 个月，{1}'.format(len(rows), '体检通过' if ok else '存在问题'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
