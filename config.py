"""爬虫全局配置"""

from datetime import date, timedelta

# ===== 12306 API 端点 =====
STATION_NAME_URL = (
    "https://kyfw.12306.cn/otn/resources/js/framework/"
    "station_name.js?station_version=1.9375"
)
LEFT_TICKET_URL = "https://kyfw.12306.cn/otn/leftTicket/queryG"
TRAIN_SCHEDULE_URL = "https://kyfw.12306.cn/otn/czxx/queryByTrainNo"
INIT_URL = "https://kyfw.12306.cn/otn/leftTicket/init"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# ===== 速率控制 =====
MAX_CONCURRENT = 8          # 最大并发数
REQUEST_INTERVAL = 0.3      # 单 worker 请求间隔 (秒)
BACKOFF_BASE = 5            # 退避基础等待 (秒)
MAX_RETRIES = 3             # 单请求最大重试次数
STOP_AFTER_NO_NEW = 200     # Phase 2: 连续 N 次无新车次则停止

# ===== 数据库路径 =====
DB_PATH = "data/railway.db"
STATIONS_JSON = "data/stations.json"
PROGRESS_DISCOVER = "data/progress_discover.json"
PROGRESS_SCHEDULES = "data/progress_schedules.json"

# ===== 查询日期 (默认 7 天后，避开预售期边界) =====
def query_date() -> str:
    return (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")


# ===== 枢纽站列表 (省会 + 直辖市 + 计划单列市 + 重要铁路枢纽) =====
# 格式: 站名 对应的电报码
HUB_STATIONS: list[dict] = [
    # --- 北京 ---
    {"name": "北京", "telecode": "BJP"},
    {"name": "北京南", "telecode": "VNP"},
    {"name": "北京西", "telecode": "BXP"},
    {"name": "北京北", "telecode": "VAP"},
    # --- 上海 ---
    {"name": "上海", "telecode": "SHH"},
    {"name": "上海虹桥", "telecode": "AOH"},
    {"name": "上海南", "telecode": "SNH"},
    # --- 天津 ---
    {"name": "天津", "telecode": "TJP"},
    {"name": "天津西", "telecode": "TXP"},
    # --- 重庆 ---
    {"name": "重庆", "telecode": "CQW"},
    {"name": "重庆北", "telecode": "CUW"},
    {"name": "重庆西", "telecode": "CXW"},
    # --- 广州 ---
    {"name": "广州", "telecode": "GZQ"},
    {"name": "广州南", "telecode": "IZQ"},
    {"name": "广州东", "telecode": "GGQ"},
    # --- 深圳 ---
    {"name": "深圳", "telecode": "SZQ"},
    {"name": "深圳北", "telecode": "IOQ"},
    # --- 杭州 ---
    {"name": "杭州", "telecode": "HZH"},
    {"name": "杭州东", "telecode": "HGH"},
    # --- 南京 ---
    {"name": "南京", "telecode": "NJH"},
    {"name": "南京南", "telecode": "NKH"},
    # --- 武汉 ---
    {"name": "武汉", "telecode": "WHN"},
    {"name": "武昌", "telecode": "WCN"},
    {"name": "汉口", "telecode": "HKN"},
    # --- 成都 ---
    {"name": "成都", "telecode": "CDW"},
    {"name": "成都东", "telecode": "ICW"},
    # --- 西安 ---
    {"name": "西安", "telecode": "XAY"},
    {"name": "西安北", "telecode": "EAY"},
    # --- 郑州 ---
    {"name": "郑州", "telecode": "ZZF"},
    {"name": "郑州东", "telecode": "ZAF"},
    # --- 济南 ---
    {"name": "济南", "telecode": "JNK"},
    {"name": "济南西", "telecode": "JGK"},
    # --- 长沙 ---
    {"name": "长沙", "telecode": "CSQ"},
    {"name": "长沙南", "telecode": "CWQ"},
    # --- 福州 ---
    {"name": "福州", "telecode": "FZS"},
    {"name": "福州南", "telecode": "FYS"},
    # --- 合肥 ---
    {"name": "合肥", "telecode": "HFH"},
    {"name": "合肥南", "telecode": "ENH"},
    # --- 南昌 ---
    {"name": "南昌", "telecode": "NCG"},
    {"name": "南昌西", "telecode": "NXG"},
    # --- 石家庄 ---
    {"name": "石家庄", "telecode": "SJP"},
    # --- 太原 ---
    {"name": "太原", "telecode": "TYV"},
    {"name": "太原南", "telecode": "TNV"},
    # --- 呼和浩特 ---
    {"name": "呼和浩特", "telecode": "HHC"},
    {"name": "呼和浩特东", "telecode": "NDC"},
    # --- 银川 ---
    {"name": "银川", "telecode": "YIJ"},
    # --- 兰州 ---
    {"name": "兰州", "telecode": "LZJ"},
    {"name": "兰州西", "telecode": "LAJ"},
    # --- 西宁 ---
    {"name": "西宁", "telecode": "XNO"},
    # --- 乌鲁木齐 ---
    {"name": "乌鲁木齐", "telecode": "WAR"},
    # --- 拉萨 ---
    {"name": "拉萨", "telecode": "LSO"},
    # --- 哈尔滨 ---
    {"name": "哈尔滨", "telecode": "HBB"},
    {"name": "哈尔滨西", "telecode": "VAB"},
    # --- 长春 ---
    {"name": "长春", "telecode": "CCT"},
    {"name": "长春西", "telecode": "CRT"},
    # --- 沈阳 ---
    {"name": "沈阳", "telecode": "SYT"},
    {"name": "沈阳北", "telecode": "SBT"},
    # --- 大连 ---
    {"name": "大连", "telecode": "DLT"},
    {"name": "大连北", "telecode": "DFT"},
    # --- 南宁 ---
    {"name": "南宁", "telecode": "NNZ"},
    {"name": "南宁东", "telecode": "NFZ"},
    # --- 昆明 ---
    {"name": "昆明", "telecode": "KMM"},
    {"name": "昆明南", "telecode": "KOM"},
    # --- 贵阳 ---
    {"name": "贵阳", "telecode": "GIW"},
    {"name": "贵阳北", "telecode": "KQW"},
    # --- 海口 ---
    {"name": "海口", "telecode": "VUQ"},
    # --- 青岛 ---
    {"name": "青岛", "telecode": "QDK"},
    {"name": "青岛北", "telecode": "QHK"},
    # --- 厦门 ---
    {"name": "厦门", "telecode": "XMS"},
    {"name": "厦门北", "telecode": "XKS"},
    # --- 宁波 ---
    {"name": "宁波", "telecode": "NGH"},
    # --- 苏州 ---
    {"name": "苏州", "telecode": "SZH"},
]

# 枢纽站电报码集合 (去重)
HUB_TELECODES: set[str] = {s["telecode"] for s in HUB_STATIONS}

# ===== 地级市/省会 中文名称集合 (用于筛选辐射站) =====
PREFECTURE_CITIES: set[str] = {
    # 直辖市 + 省会已包含在枢纽站中，此处列出所有地级市
    # 河北
    "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水",
    # 山西
    "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁",
    # 内蒙古
    "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布",
    # 辽宁
    "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛",
    # 吉林
    "吉林", "四平", "辽源", "通化", "白山", "松原", "白城", "延边",
    # 黑龙江
    "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化",
    # 江苏
    "无锡", "徐州", "常州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁",
    # 浙江
    "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
    # 安徽
    "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城",
    # 福建
    "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德",
    # 江西
    "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶",
    # 山东
    "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽",
    # 河南
    "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店",
    # 湖北
    "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施",
    # 湖南
    "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底",
    # 广东
    "韶关", "珠海", "汕头", "佛山", "江门", "湛江", "茂名", "肇庆", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮",
    # 广西
    "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林", "百色", "贺州", "河池", "来宾", "崇左",
    # 海南
    "三亚", "儋州", "三沙",
    # 四川
    "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳",
    # 贵州
    "六盘水", "遵义", "安顺", "毕节", "铜仁",
    # 云南
    "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧",
    # 西藏
    "日喀则", "昌都", "林芝", "山南", "那曲",
    # 陕西
    "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛",
    # 甘肃
    "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西", "陇南",
    # 青海
    "海东",
    # 宁夏
    "石嘴山", "吴忠", "固原", "中卫",
    # 新疆
    "克拉玛依", "吐鲁番", "哈密",
}
