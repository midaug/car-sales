# car-sales

[![数据更新](https://github.com/midaug/car-sales/actions/workflows/start_spider.yml/badge.svg)](https://github.com/midaug/car-sales/actions/workflows/start_spider.yml) ![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue) ![MIT License](https://img.shields.io/badge/License-MIT-green)

一个纯前端的汽车销量排行榜：按车系、厂商、品牌或集团查看月度与年度销量，支持按级别、能源类型和价格段筛选，并可导出 CSV。数据以静态文件形式保存在仓库中，页面直接读取，无需后端服务。

> 数据仅供研究和学习参考，不构成任何购买建议。

## 功能特性

- **月 / 年双视图**：时间轴连续覆盖 2020 年 2 月至今，随自动更新持续延长。
- **四种聚合维度**：车系明细、按厂商合并、按品牌合并、按集团合并。
- **集团归属口径**：合资厂商可按「品牌方 / 中方 / 双计」切换；华为系作为叠加归属并入集团榜，与自有集团重复计入。
- **多维筛选**：
  - 能源：燃油车（含油电混动）、新能源、纯电、插混、增程、双动力（同一车系同时有纯电与增程版本）；
  - 级别：轿车 / SUV / MPV / 跑车，按微型至大型的尺寸段细分，组头可一键全选；
  - 价格段：10 万以下至 50 万以上共 6 档，按指导价中值归档；
  - 关键词搜索：支持品牌与车系名称。
- **数据呈现**：排名、销量、占比、环比趋势，悬浮（移动端点按）查看车系与品牌明细，支持一键导出 CSV。
- **响应式布局**：桌面端与手机端均可使用。
- **数据体检**：自动检查缺月、内容重复的月份和损坏文件，异常会让更新任务失败。

## 在线查看

<https://car-sales-taupe.vercel.app/>

如果线上地址暂时不可达，可以按下面的方式在本地启动。

## 本地运行

```bash
git clone https://github.com/midaug/car-sales.git
cd car-sales
python3 -m http.server 8080
```

浏览器打开 <http://localhost:8080/docs/index.html> 即可。页面通过 CDN 读取仓库 `data/` 目录下的数据文件，因此本地预览需要联网；项目本身没有构建步骤，也没有后端依赖。

## 目录结构

```text
car-sales/
├── docs/
│   └── index.html                  # 单文件前端：样式、交互、数据加载
├── data/
│   ├── last_date.js                # 当前最新月份
│   ├── YYYY/
│   │   ├── MM/
│   │   │   ├── car_all.js          # 当月全量车系销量
│   │   │   ├── car_new_energy.js   # 当月新能源车系销量
│   │   │   └── energy.js           # 车系 ID -> 能源类型
│   │   └── year_merge-*.js         # 年度合并数据
│   └── ...
├── spider_dcd.py                   # 数据更新脚本
├── check_data.py                   # 数据体检脚本
├── .github/workflows/start_spider.yml
└── README.md
```

## 数据格式

月度数据以 `window.sessionStorage.setItem(key, json)` 的形式保存，浏览器加载后直接解析：

```js
window.sessionStorage.setItem('car_all_202610', '{"order":["car_4865", "..."], "car_4865":{"series_id":4865,"series_name":"...","count":13257,"brand_name":"...","sub_brand_name":"...","outter_detail_type":13,"price":"...","rank":1,"last_rank":2,"image":"..."}}');
```

主要字段：

| 字段 | 说明 |
| --- | --- |
| `series_id` | 车系 ID |
| `series_name` | 车系名称 |
| `count` | 当月销量（辆） |
| `brand_name` / `sub_brand_name` | 品牌 / 厂商名称 |
| `outter_detail_type` | 车型级别编码，前端映射为轿车 / SUV / MPV / 跑车及尺寸段 |
| `price` | 指导价区间 |
| `rank` / `last_rank` | 本月 / 上月排名 |
| `image` | 车系图片地址 |

`energy.js` 保存 `series_id -> 类型` 的映射：`1` 纯电、`2` 插混、`3` 增程、`4` 双动力。早期月份的能源细分覆盖不完整，页面会给出提示。

年度视图读取 `year_merge-car_all.js`、`year_merge-car_new_energy.js` 和 `year_merge-energy.js`；这些文件由更新脚本在每月数据写完后重建。

2020 年 2 月的月度文件带有 `_est: "202003"` 标记，表示该月按相邻月份回填，属于估算值，页面会显式标注，避免与真实数据混淆。

## 自动更新

GitHub Actions 工作流每天运行两次（UTC 01:00 / 13:00，即北京时间 09:00 / 21:00），流程为：

1. 运行 `spider_dcd.py` 更新月度数据并重建年度文件；
2. 运行 `check_data.py` 做数据体检；
3. 仅在数据发生变化时提交并推送；
4. 刷新 CDN 缓存，让页面尽快看到新数据。

也可以在仓库的 Actions 页面手动触发 `start_spider`。本地更新：

```bash
pip install requests python-dateutil
python3 spider_dcd.py
python3 check_data.py
```

可选环境变量：

| 变量 | 作用 |
| --- | --- |
| `START_MONTH` | 起始月份，默认 `202002` |
| `FORCE_MONTHS` | 强制重抓的月份，多个用逗号分隔，例如 `FORCE_MONTHS=202502,202503` |

更新脚本会校验数据是否与相邻月份或已有快照重复，发现异常会跳过写入并在日志中标记；真实失败会让任务以非 0 状态退出。

## 数据体检

```bash
python3 check_data.py             # 全部月份
python3 check_data.py 2025 2026   # 只看指定年份
```

检查项包括自然月缺口、内容完全重复的月份、为空或损坏的文件，并输出每月车系数、总销量、冠军车系及年度合计。存在异常时退出码为 `1`，因此可以直接接入 CI。估算月份会单列显示，不会误判为重复数据。

## 参与贡献

欢迎通过 Issue 或 Pull Request 改进：

- 品牌别名与历史名称合并规则；
- 集团归属、合资双向归属映射；
- 数据异常反馈与修复；
- 前端交互、性能与可访问性优化。

提交前请先运行 `python3 check_data.py`，并在 PR 中说明数据或规则变更的原因。

## 许可证

MIT License

Copyright (c) 2026 midaug

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
