# -*- coding: UTF8 -*-
import json
import requests
import warnings
import traceback
from requests.packages import urllib3
import os
import time
from datetime import datetime
from dateutil.relativedelta import relativedelta

urllib3.disable_warnings()
warnings.filterwarnings("ignore")

# 数据保存目录
data_path = './data'


def replaceStr(s=''):
    return s.replace(' ', '').replace(',', '')


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


def requestCarData(url, dataPath, dir, dateStr):
    # 当文件存在是读取文件数据
    if os.path.exists(dataPath):
        try:
            f = open(dataPath, 'r', encoding="utf8")
            dataStr = f.read()
            f.close()
            print('info dataPath exists: {0}'.format(dataPath))
            return dataStr
        except:
            return None
    data = {}
    # 文件不存在时发起请求下载
    try:
        response = requests.get(url=url, verify=False)
        response = response.json()
        print('request url={0} , response.status={1} , data.list.len={2}'.format(url, response['status'], len(response['data']['list'])))
        if 0 == response['status']:
            order = []
            for carSales in response['data']['list']:
                del carSales['offline_car_ids']
                del carSales['online_car_ids']
                key = '{0}_{1}'.format('car', carSales['series_id'])
                data[key] = carSales
                order.append(key)
            data['order'] = order
            dataStr = json.dumps(data, ensure_ascii=False)
            mkdir(dir)
            wFile(dataStr, dataPath)
            wFile("window.sessionStorage.setItem('last_date','{0}')".format(dateStr), data_path + "/last_date.js")
            return dataStr
        else:
            print('Failed requests error, url={0}, response={1}'.format(url, response))
            return None
    except:
        traceback.print_exc()
        print('Failed requests error, url={} \n'.format(url))
        return None


def start(url, dateStr, car_type):
    fileDir = '{dir}/{year}/{month}'.format(dir=data_path, year=dateStr[:4], month=dateStr[4:6])
    allCarPath = '{dir}/{type}.json'.format(dir=fileDir, type=car_type)
    allCarJsPath = '{dir}/{type}.js'.format(dir=fileDir, type=car_type)
    carData = requestCarData(url, allCarPath, fileDir, dateStr)
    if not os.path.exists(allCarJsPath) and not carData is None:
        return wFile("window.sessionStorage.setItem('{0}_{1}', '{2}')".format(car_type, dateStr, carData), allCarJsPath)


def mergeYear(car_type):
    years = [f for f in os.listdir(data_path) if os.path.isdir(data_path + '/' + f)]
    for year in years:
        year_path = data_path + "/" + year
        allCarPath = '{dir}/year_merge-{type}.json'.format(dir=year_path, type=car_type)
        allCarJsPath = '{dir}/year_merge-{type}.js'.format(dir=year_path, type=car_type)
        dataMap = {}
        months = [year_path + '/' + f for f in os.listdir(year_path) if os.path.isdir(year_path + '/' + f)]
        for month in months:
            filePath =  '{dir}/{type}.json'.format(dir=month, type=car_type)
            if os.path.exists(filePath):
                try:
                    f = open(filePath, 'r', encoding="utf8")
                    cars = json.loads(f.read())
                    for key in cars:
                        if 'order' == key:
                            continue
                        data = {}
                        if key in dataMap:
                            data = dataMap[key]
                            data['count'] = data['count'] + cars[key]['count']
                        else:
                            data = cars[key]
                        dataMap[key] = data
                    f.close()
                except Exception as e: 
                    print(e)
                    print('Failed mergeYear error, path={} \n'.format(filePath))
        dataMap['order'] = [key for key in dataMap]
        dataStr = json.dumps(dataMap, ensure_ascii=False)
        mkdir(year_path)
        wFile(dataStr, allCarPath)
        if not os.path.exists(allCarJsPath) and not dataStr is None:
            wFile("window.sessionStorage.setItem('{0}_{1}', '{2}')".format('year_merge-' + car_type, year, dataStr), allCarJsPath)


if __name__ == "__main__":
    # 全部车型url
    car_all_url = 'https://www.xxx.com/motor/pc/car/rank_data?aid=1839&app_name=auto_web_pc&city_name=&count=10000&offset=0&month={0}&new_energy_type=&rank_data_type=11&brand_id=&price=&manufacturer=&outter_detail_type=&nation=0'
    # 新能源销量url
    car_new_energy_url = 'https://www.xxx.com/motor/pc/car/rank_data?aid=1839&app_name=auto_web_pc&city_name=&count=10000&offset=0&month={0}&new_energy_type=1%2C2%2C3&rank_data_type=11&brand_id=&price=&manufacturer=&outter_detail_type=&nation=0'
    # 开始时间
    start_month = '202002'
    # start_month = '202308'
    # 时间格式化
    format_str = '%Y%m'
    # 截至时间，默认为当前月
    end_month = datetime.strftime(datetime.now() - relativedelta(months=1), format_str)
    # 创建数据存储目录
    mkdir(data_path)
    try:
        while start_month != end_month:
            start_month_date = datetime.strptime(start_month, format_str)
            start_month = datetime.strftime(start_month_date + relativedelta(months=1), format_str)
            start(car_all_url.format(start_month), start_month, 'car_all')
            start(car_new_energy_url.format(start_month), start_month, 'car_new_energy')
        mergeYear('car_all')
        mergeYear('car_new_energy')
        print('Finished')
    except:
        traceback.print_exc()
        print('error')
