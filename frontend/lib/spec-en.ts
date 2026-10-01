/**
 * 规格值「值级翻译」工具（仅英文模式启用）。
 *
 * 参数对比页的规格值来自桌面参数表 Excel（自由文本），混有大量中文标注
 * （如「2025年1月(欧洲)」「主摄: 50MP」「2600nits峰值」「极客湾综合性能」）。
 * 这些是数据而非 UI 文案，无法用 t() 词典覆盖，因此用有序规则做正则替换，
 * 把常见中文模式转成英文。中文模式保持原样、不经过本函数。
 *
 * 规则顺序敏感：长组合规则必须先于短规则（如「潜望长焦」先于「长焦」、
 * 「不支持」先于「支持」、「屏下指纹」先于「屏」）。
 * TERM 规则统一带前导空格，避免替换后与前文粘连（如「45W快充」→"45W fast charging"）。
 * 未覆盖的罕见词残留中文可接受。
 */

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const REGION: Record<string, string> = {
  全球: "Global",
  欧洲: "Europe",
  中国: "China",
  海外: "overseas",
  德国: "Germany",
  美国: "US",
  印度: "India",
  亚太: "APAC",
};

type SpecRule = [
  RegExp,
  string | ((substring: string, ...args: string[]) => string),
];

/** 前置规则（带上下文的长组合，最先执行；自带上/后空格） */
const PRE_RULES: SpecRule[] = [
  // 日期：2025年1月24日 → Jan 24, 2025 ；2025年1月 → Jan 2025 ；2026年Q1 → Q1 2026
  [
    /(\d{4})年(\d{1,2})月(\d{1,2})日/g,
    (_m, y: string, mo: string, d: string) =>
      `${MONTHS[Number(mo) - 1] ?? mo} ${Number(d)}, ${y}`,
  ],
  [
    /(\d{4})年(\d{1,2})月/g,
    (_m, y: string, mo: string) => `${MONTHS[Number(mo) - 1] ?? mo} ${y}`,
  ],
  [/(\d{4})年Q(\d)/g, "Q$2 $1"],
  // 地区括号（斜杠连写与单 token）
  [/\(全球\/欧洲\)/g, " (Global/Europe)"],
  [/\(欧洲MWC\)/g, " (Europe MWC)"],
  [
    /\((全球|欧洲|中国|海外|德国|美国|印度|亚太)\)/g,
    (_m, r: string) => ` (${REGION[r] ?? r})`,
  ],
  [/\(官网独占\)/g, " (website-exclusive)"],
  [/\(白色\)/g, " (white)"],
  [/\(暖白\)/g, " (warm white)"],
  [/\(黑色\)/g, " (black)"],
  [/\(其他\)/g, " (others)"],
  [/\(玻璃\)/g, " (glass)"],
  [/\(素皮\)/g, " (vegan leather)"],
  [/\(纳米皮\)/g, " (nano leather)"],
  // 分类（独立单元格值，无需前导空格）
  [/旗舰机/g, "Flagship"],
  [/中端机/g, "Mid-range"],
  [/入门机/g, "Entry-level"],
  [/折叠机/g, "Foldable"],
  // 摄像头：带冒号的标注形式
  [/主摄[:：]/g, "Main: "],
  [/超广角[:：]/g, "Ultra-wide: "],
  [/微距[:：]/g, "Macro: "],
  [/景深[:：]/g, "Depth: "],
  [/潜望长焦/g, " periscope tele"],
  [/超长焦/g, " super-tele"],
  [/浮动长焦/g, " floating tele"],
  [/双长焦/g, " dual tele"],
  [/深感摄像头/g, " depth camera"],
  [/自动对焦/g, " AF"],
  [/光学防抖/g, " optical stabilization"],
  [/光学变焦/g, " optical zoom"],
  [/无损变焦/g, " lossless zoom"],
  [/(\d+)级防抖/g, "$1-class stabilization"],
  // 像素 → MP（支持 1.08亿=108MP / 2亿=200MP / 5000万=50MP）
  [
    /(\d+(?:\.\d+)?)亿像素/g,
    (_m, n: string) => `${Math.round(Number(n) * 100)}MP`,
  ],
  [
    /(\d+(?:\.\d+)?)万像素/g,
    (_m, n: string) => `${Math.round(Number(n) / 100)}MP`,
  ],
  // 芯片跑分（极客湾 → Geekerwan）
  [/综合性能[:：]/g, "score: "],
  [/极客湾/g, "Geekerwan "],
  // 单位 / 尺寸标注
  [/(\d+(?:\.\d+)?)英寸/g, "$1-inch"],
  [/四等深微曲屏/g, " quad-depth micro-curved display"],
  [/全等深微曲屏/g, " full-depth micro-curved display"],
  [/等深微曲屏/g, " micro-curved display"],
  [/四曲屏/g, " quad-curved display"],
  [/微曲屏/g, " micro-curved display"],
  [/隐私防窥屏/g, " privacy display"],
  [/屏下摄像头/g, " under-display camera"],
  [/屏下指纹/g, " in-display fingerprint"],
  [/内屏摄像头/g, " inner display camera"],
  [/外屏摄像头/g, " outer display camera"],
  [/曲面AMOLED屏/g, " curved AMOLED display"],
  [/小直屏/g, " compact flat-display"],
  [/直屏/g, " flat display"],
  [/全面屏/g, " full-screen"],
  [/重量[:：]/g, "Weight: "],
  [/展开[:：]/g, "Unfolded: "],
  [/折叠[:：]/g, "Folded: "],
  [/约(?=\d)/g, "~"],
  [/(\d+)分钟充满/g, " full charge in $1 min"],
  [/(\d+)天续航/g, "$1-day battery life"],
  [/性能性价比之王/g, " performance-value king"],
  [/高配版/g, " high-end variant"],
  [/无IP认证/g, "No IP rating"],
  [/点击查看官网/g, "Click to view official website"],
  [/双快充/g, " dual fast charging"],
  [/双路充电/g, " dual-path charging"],
  [/光学品质变焦/g, " optical-quality zoom"],
  [/光学镜头/g, " optical lens"],
  [/打孔前摄/g, " punch-hole front camera"],
  [/一英寸/g, " 1-inch"],
  [/钛金属/g, " titanium "],
  [/可变光圈/g, " variable aperture"],
  [/护照式/g, " passport-style"],
  [/全新/g, " new"],
  [/宽屏/g, " wide display"],
  [/减折痕/g, " reduces crease"],
  [/系统更新至/g, " system updates until"],
  [/离线通讯/g, " offline comm"],
  [/电影级/g, " cinema-grade"],
  [/杜比视界/g, " Dolby Vision"],
  [/三50MP/g, " triple 50MP"],
  [/超拟人/g, " ultra-human-like"],
  [/更新至/g, " updates until"],
  [/智能推送/g, " smart notifications"],
  [/大视野/g, " wide-view"],
  [/光学系统/g, " optical system"],
  [/超纯/g, " ultra-pure"],
  [/比例/g, " aspect ratio"],
  [/深度集成/g, " deep integration"],
  [/(\d+)点(?=[A-Za-z])/g, "$1-point "],
  [/(\d{4})年/g, " $1"],
  [/小米金沙江电池/g, " Xiaomi Jinsha River battery"],
  [/第三代硅碳电池/g, " 3rd-gen silicon-carbon battery"],
  [/硅碳电池/g, " silicon-carbon battery"],
  [/支持手写笔/g, " stylus support"],
  [/图像\/视频/g, " image/video"],
];

/** 常用术语表（前导空格版本；顺序仍敏感，长词在前） */
const TERM_RULES: Array<[RegExp, string]> = [
  // 词序敏感组合
  [/金属一体化机身/g, " metal unibody"],
  [/一体化机身/g, " unibody"],
  [/全球最薄/g, " world's thinnest"],
  [/抗摔架构/g, " drop-resistant build"],
  [/超大光圈/g, " large aperture"],
  [/高性价比/g, " great value"],
  [/超声波指纹/g, " ultrasonic fingerprint"],
  [/深度伪造/g, " deepfake"],
  [/图像转视频/g, " image-to-video"],
  [/环绕低音炮/g, " surround subwoofer"],
  [/系统更新/g, " system updates"],
  [/OS更新/g, " OS updates"],
  [/安全更新/g, " security updates"],
  [/电池健康/g, " battery health"],
  [/低温充电/g, " low-temp charging"],
  [/跨生态/g, " cross-ecosystem"],
  [/毫米波/g, " mmWave"],
  [/抗老化/g, " anti-aging"],
  [/等效/g, " equivalent"],
  [/官网独占/g, " website-exclusive"],
  // 摄像头裸词
  [/主摄/g, " main camera"],
  [/超广角/g, " ultra-wide"],
  [/长焦/g, " tele"],
  [/微距/g, " macro"],
  [/景深/g, " depth"],
  [/像素/g, "MP"],
  [/相机/g, " camera"],
  [/人脸识别/g, " face unlock"],
  [/双解锁/g, " dual unlock"],
  [/指纹/g, " fingerprint"],
  [/人脸/g, " face"],
  // 屏 / 显示
  [/可折叠/g, " foldable"],
  [/折叠屏/g, " foldable display"],
  [/阳光屏/g, " sunlight display"],
  [/展开/g, " unfolded"],
  [/折叠/g, " folded"],
  [/曲面/g, " curved "],
  [/内屏/g, " inner display"],
  [/外屏/g, " outer display"],
  [/超亮/g, " ultra-bright"],
  [/全尺寸/g, " full-size"],
  [/大屏/g, " large display"],
  [/超大屏/g, " ultra-large display"],
  [/屏幕/g, " display"],
  [/屏/g, " display"],
  [/峰值/g, " peak"],
  // 充电 / 供电
  [/超级快充/g, " super fast charging"],
  [/快充/g, " fast charging"],
  [/无线/g, " wireless"],
  [/有线/g, " wired"],
  [/充电/g, " charging"],
  [/不支持/g, " Not supported"],
  // 电池 / 机身 / 材料
  [/超大电池/g, " ultra-large battery"],
  [/最大电池/g, " largest battery"],
  [/硅碳/g, " silicon-carbon"],
  [/新一代/g, " next-gen"],
  [/大电池/g, " large battery"],
  [/电池/g, " battery"],
  [/超薄/g, " ultra-thin"],
  [/最薄/g, " thinnest"],
  [/超轻/g, " ultra-light"],
  [/轻薄/g, " slim & light"],
  [/轻量/g, " lightweight"],
  [/一体化/g, " unibody"],
  [/金属/g, " metal"],
  [/机身/g, " body"],
  [/玻璃/g, " glass"],
  [/纳米皮/g, " nano leather"],
  [/素皮/g, " vegan leather"],
  // 功能词
  [/耳机孔/g, " headphone jack"],
  [/防水/g, " waterproof"],
  [/防抖/g, " stabilization"],
  [/抗摔/g, " drop resistance"],
  [/对焦/g, " focusing"],
  [/广角/g, " wide-angle"],
  [/变焦/g, " zoom"],
  [/摄像头/g, " camera"],
  [/双摄/g, " dual camera"],
  [/徕卡/g, " Leica"],
  [/水深/g, " water depth"],
  [/按键/g, " key"],
  [/生成/g, " generation"],
  [/图像/g, " image"],
  [/视频/g, " video"],
  [/检测/g, " detection"],
  [/估算/g, " estimate"],
  [/眼舒适/g, " eye comfort"],
  [/保时捷/g, " Porsche"],
  [/小米/g, " Xiaomi"],
  [/金沙江/g, " Jinsha River"],
  [/骁龙/g, " Snapdragon "],
  [/天玑/g, " Dimensity "],
  [/智能体/g, " AI agent"],
  [/生产力/g, " productivity"],
  [/互联/g, " connectivity"],
  [/扩展/g, " expansion"],
  [/解锁/g, " unlock"],
  [/手写笔/g, " stylus"],
  [/按钮/g, " button"],
  [/按键/g, " key"],
  [/超大/g, " ultra-large"],
  [/反向充电/g, " reverse charging"],
  [/双扬声器/g, " dual speakers"],
  [/立体声/g, " stereo"],
  [/跌落防护/g, " drop protection"],
  [/防反光/g, " anti-glare"],
  [/设计语言/g, " design language"],
  [/旗舰芯/g, " flagship chip"],
  [/旗舰/g, " flagship"],
  [/性能/g, " performance"],
  [/之王/g, " king"],
  [/单核/g, " single-core"],
  [/新中端/g, " new mid-range"],
  [/中端/g, " mid-range"],
  [/独有/g, " exclusive"],
  [/集成/g, " integration"],
  [/澎湃/g, " Surge"],
  [/音量/g, " volume"],
  [/认证/g, " certified"],
  [/钛金属/g, " titanium"],
  [/边框/g, " frame"],
  [/续航/g, " battery life"],
  [/升级/g, " upgrade"],
  [/三星/g, "Samsung"],
  [/最轻/g, " lightest"],
  [/史上/g, "ever"],
  [/分辨率/g, " resolution"],
  [/全局/g, " global"],
  [/合并/g, " merging"],
  [/辅助镜头/g, " auxiliary lens"],
  [/前摄/g, " front camera"],
  [/矩阵/g, " matrix"],
  [/可变/g, " variable"],
  [/超窄/g, " ultra-narrow"],
  [/光纤版/g, " fiber version"],
  [/玻璃版/g, " glass version"],
  [/纤维版/g, " fiber version"],
  [/版/g, " version"],
  [/技术/g, " tech"],
  [/设计/g, " design"],
  [/折痕/g, " crease"],
  [/离线/g, " offline"],
  [/助理/g, " assistant"],
  [/引擎/g, " engine"],
  [/影像/g, " imaging"],
  [/级别/g, "-grade"],
  [/最强/g, " best"],
  [/三摄/g, " triple camera"],
  [/四摄/g, " quad camera"],
  [/八焦段/g, " 8 focal lengths"],
  [/全明星/g, " all-star"],
  [/无(?=\s)/g, "no"],
  [/增(?=\d+%)/g, "+"],
  [/超声波/g, " ultrasonic"],
  [/镜头/g, " lens"],
  [/空间/g, " space"],
  [/纤维版/g, " fiber version"],
  [/荣耀/g, "DemoBrand "],
  [/(\d+)倍/g, "$1x"],
  [/反向/g, " reverse"],
  [/钛/g, " titanium"],
  [/系列/g, " series"],
  [/最大/g, " largest"],
  [/索尼/g, " Sony"],
  [/触控/g, " touch"],
  [/双(?=\d)/g, " dual "],
  [/无(?=[A-Za-z0-9])/g, "no "],
  [/安卓更新/g, " Android updates"],
  [/更新/g, " updates"],
  [/五星/g, " 5-star"],
  [/超级/g, " super"],
  [/超值/g, " great value"],
  [/性价比/g, " value"],
  [/入门/g, " entry-level"],
  [/传感器/g, " sensor"],
  [/超夜/g, " ultra-night"],
  [/支持/g, " supports"],
  [/(\d+)核/g, "$1-core"],
  [/(\d+)年/g, "$1 years"],
];

/** 收尾：修复替换产生的粘连、残留中文与多余空格 */
function postProcess(s: string): string {
  // 替换产出的英文词后紧跟字母/数字（如 200MPOIS / 45Wfast / cameraOIS / level4G）
  s = s.replace(
    /(MP|mAh|years|camera|tele|zoom|display|battery|charging|fingerprint|stabilization|expansion|updates|supports|body|glass|leather|value|level|score|estimate|generation|key|aperture|Leica|folded|unfolded|like)([A-Za-z0-9])/g,
    "$1 $2",
  );
  // 残留中文与相邻拉丁/数字之间加空格（可读性兜底）
  s = s.replace(/([\u4e00-\u9fff])([A-Za-z0-9])/g, "$1 $2");
  s = s.replace(/([A-Za-z0-9])([\u4e00-\u9fff])/g, "$1 $2");
  // 括号内清理
  s = s.replace(/\(\s+/g, "(").replace(/\s+\)/g, ")");
  // 空格规整
  s = s.replace(/ +/g, " ").replace(/ ,/g, ",").replace(/ ;/g, ";");
  return s.trim();
}

export function toEnglishSpec(raw: string): string {
  if (!raw) return raw;
  let s = String(raw);
  for (const [re, rep] of PRE_RULES) {
    s = s.replace(re, rep as string);
  }
  for (const [re, rep] of TERM_RULES) {
    s = s.replace(re, rep);
  }
  return postProcess(s);
}
