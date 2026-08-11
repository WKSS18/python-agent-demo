from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf" / "王浩-高级前端开发工程师-优化版.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

pdfmetrics.registerFont(TTFont("YaHei", r"C:\Windows\Fonts\msyh.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("YaHeiBold", r"C:\Windows\Fonts\msyhbd.ttc", subfontIndex=0))

NAVY = colors.HexColor("#16324F")
TEAL = colors.HexColor("#087E8B")
INK = colors.HexColor("#243342")
MUTED = colors.HexColor("#607080")
LIGHT = colors.HexColor("#F3F7F8")
LINE = colors.HexColor("#DCE6E9")
WHITE = colors.white

styles = getSampleStyleSheet()
base = ParagraphStyle("base", fontName="YaHei", fontSize=8.7, leading=13.2, textColor=INK, spaceAfter=2.5)
small = ParagraphStyle("small", parent=base, fontSize=7.6, leading=11.2, textColor=MUTED)
name_style = ParagraphStyle("name", fontName="YaHeiBold", fontSize=25, leading=30, textColor=NAVY)
role_style = ParagraphStyle("role", fontName="YaHei", fontSize=10.5, leading=16, textColor=TEAL)
section_style = ParagraphStyle("section", fontName="YaHeiBold", fontSize=12.5, leading=17, textColor=NAVY, spaceBefore=5, spaceAfter=6)
job_style = ParagraphStyle("job", fontName="YaHeiBold", fontSize=9.3, leading=14, textColor=NAVY)
meta_style = ParagraphStyle("meta", fontName="YaHei", fontSize=7.5, leading=11, textColor=MUTED)
project_title = ParagraphStyle("project", fontName="YaHeiBold", fontSize=10, leading=14, textColor=NAVY)
card_title = ParagraphStyle("card_title", fontName="YaHeiBold", fontSize=10.3, leading=14, textColor=WHITE)
card_body = ParagraphStyle("card_body", fontName="YaHei", fontSize=8.1, leading=12, textColor=WHITE)
footer_style = ParagraphStyle("footer", fontName="YaHei", fontSize=7, textColor=MUTED, alignment=TA_CENTER)


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 13 * mm, 192 * mm, 13 * mm)
    canvas.setFont("YaHei", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.5 * mm, "王浩 · 高级前端开发工程师")
    canvas.drawRightString(192 * mm, 8.5 * mm, f"{doc.page}")
    canvas.restoreState()


doc = BaseDocTemplate(
    str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
    topMargin=14 * mm, bottomMargin=17 * mm, title="王浩 - 高级前端开发工程师简历",
    author="王浩",
)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
doc.addPageTemplates([PageTemplate(id="resume", frames=frame, onPage=header_footer)])


def P(text, style=base):
    return Paragraph(text, style)


def section(title):
    return KeepTogether([
        P(title, section_style),
        Table([[""]], colWidths=[doc.width], rowHeights=[1], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL),
        ])),
        Spacer(1, 4),
    ])


def bullets(items, style=base):
    return [P(f"<font color='#087E8B'>●</font>&nbsp; {item}", style) for item in items]


def job(company, role, dates, summary):
    title = Table([
        [P(f"{company}｜{role}", job_style), P(dates, meta_style)],
    ], colWidths=[doc.width - 38 * mm, 38 * mm], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return KeepTogether([title, P(summary, base), Spacer(1, 4)])


def project(name, role, dates, stack, points):
    title = Table([[P(f"{name}  <font color='#087E8B'>· {role}</font>", project_title), P(dates, meta_style)]],
                  colWidths=[doc.width - 38 * mm, 38 * mm], style=TableStyle([
                      ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                      ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                  ]))
    stack_bar = Table([[P(f"<b>技术栈</b>&nbsp;&nbsp;{stack}", meta_style)]], colWidths=[doc.width], style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), .35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    content = [title, Spacer(1, 2), stack_bar, Spacer(1, 2)] + bullets(points, base) + [Spacer(1, 7)]
    return KeepTogether(content)


story = []

# Page 1
top = Table([
    [P("王 浩", name_style), P("31 岁&nbsp;&nbsp;｜&nbsp;&nbsp;上海&nbsp;&nbsp;｜&nbsp;&nbsp;离职 1 周到岗<br/>157-5823-0168&nbsp;&nbsp;｜&nbsp;&nbsp;w1455068403@163.com", ParagraphStyle("contact", parent=base, alignment=2, fontSize=8.5, leading=14))],
    [P("高级前端开发工程师 · 6 年经验", role_style), P("期望薪资：面议", ParagraphStyle("salary", parent=small, alignment=2))],
], colWidths=[95 * mm, doc.width - 95 * mm], style=TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
]))
story += [top, Spacer(1, 5)]

cards = Table([
    [P("AI 知识笔记", card_title), P("凌霄 AI", card_title)],
    [P("RAG 知识库 · SSE 流式问答 · 文档解析/Embedding<br/><link href='http://43.139.122.160' color='#FFFFFF'><u>http://43.139.122.160</u></link>", card_body),
     P("企业 AI Chat · 知识库 · PDF 引用定位<br/><link href='https://os.smartbuddy.me' color='#FFFFFF'><u>https://os.smartbuddy.me</u></link>", card_body)],
], colWidths=[doc.width / 2 - 3 * mm, doc.width / 2 - 3 * mm], style=TableStyle([
    ("BACKGROUND", (0, 0), (0, -1), NAVY), ("BACKGROUND", (1, 0), (1, -1), TEAL),
    ("BOX", (0, 0), (0, -1), 0.5, NAVY), ("BOX", (1, 0), (1, -1), 0.5, TEAL),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
    ("TOPPADDING", (0, 1), (-1, 1), 2), ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
    ("LEFTPADDING", (1, 0), (1, -1), 10),
    ("RIGHTPADDING", (0, 0), (0, -1), 10),
]))
story += [cards, Spacer(1, 6), section("个人优势")]
story += [P("6 年 React 技术栈经验，聚焦 <b>AI 应用前端与复杂中后台</b>。具备 AI Chat、RAG 知识库、SSE 流式交互、PDF 引用定位及 Nest.js/Python 全栈协作经验，可从技术方案、架构设计推进到线上交付。主导组件库、微前端和性能专项，曾实现构建提速 3 倍、LCP 2.5s→1.2s、万级列表流畅渲染。")]

story += [section("核心能力")]
skills = [
    [P("AI 应用", job_style), P("AI Chat · RAG · SSE 流式渲染 · 引用溯源 · PDF 定位 · 文档解析", base)],
    [P("前端架构", job_style), P("React / Vue3 · TypeScript · Zustand / Redux · Vite / Rsbuild / Webpack", base)],
    [P("工程与性能", job_style), P("组件库 · 微前端 · 虚拟列表 · 拆包/Gzip · LCP · 弱网恢复", base)],
    [P("全栈与跨端", job_style), P("Nest.js · Python · MySQL · MongoDB · React Native / Expo · Three.js", base)],
]
story += [Table(skills, colWidths=[28 * mm, doc.width - 28 * mm], style=TableStyle([
    ("BACKGROUND", (0, 0), (0, -1), LIGHT), ("GRID", (0, 0), (-1, -1), .35, LINE),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))]

story += [section("工作经历")]
story += [
    job("软通动力", "资深前端开发工程师", "2026.03 - 2026.07", "负责企业级 AI 智能平台前端，主导 AI Chat、知识库管理、PDF 引用定位等核心模块架构与交付。"),
    job("维信金科", "Web 高级前端开发工程师", "2022.11 - 2026.02", "前端技术骨干，负责 AI Agent、React/Vue3 混合栈、组件库、催收系统、策略引擎和 OA 重构，统筹多业务线方案落地。"),
    job("58 集团（安居客）", "Web 高级前端开发工程师", "2020.05 - 2022.09", "负责人审中台微前端架构与房产 CMS/全景项目，支持多子应用独立发布，运营效率提升约 40%。"),
]
story += [section("代表成果")]
achievements = Table([
    [P("<b>3×</b><br/><font size='7'>构建效率提升</font>", ParagraphStyle("metric", parent=base, alignment=TA_CENTER, textColor=NAVY)),
     P("<b>50+</b><br/><font size='7'>通用组件沉淀</font>", ParagraphStyle("metric2", parent=base, alignment=TA_CENTER, textColor=NAVY)),
     P("<b>1.2s</b><br/><font size='7'>首页 LCP 优化后</font>", ParagraphStyle("metric3", parent=base, alignment=TA_CENTER, textColor=NAVY)),
     P("<b>95%</b><br/><font size='7'>跨端代码复用</font>", ParagraphStyle("metric4", parent=base, alignment=TA_CENTER, textColor=NAVY))],
], colWidths=[doc.width / 4] * 4, rowHeights=[15 * mm], style=TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("GRID", (0, 0), (-1, -1), .4, LINE),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
]))
story += [achievements]
story.append(PageBreak())

# Page 2
story += [section("AI 项目经历")]
story += [
    project("AI 知识笔记", "个人作品", "2026.05 - 2026.08", "React · TypeScript · FastAPI · MySQL · Qdrant · SSE · Docker",
            ["<b>项目定位：</b>面向个人知识管理的 AI 应用，支持笔记与文档导入、RAG 检索、引用溯源和 SSE 流式问答。",
             "<b>个人职责：</b>独立完成前端交互、FastAPI 接口、MySQL/Qdrant 数据链路及 Docker + Nginx 腾讯云部署。",
             "<b>在线体验：</b><link href='http://43.139.122.160' color='#087E8B'><u>http://43.139.122.160</u></link>。"]),
    project("凌霄 AI 企业智能平台", "前端核心开发", "2026.03 - 2026.07", "React · TypeScript · Ant Design · Vite · pdf.js · SSE · Python",
            ["<b>项目背景：</b>企业级 AI 办公平台，覆盖 AI Chat、知识库、合同审核、模板管理和定时任务。",
             "<b>核心职责：</b>负责流式输出、知识库管理、PDF 预览与引用定位高亮，封装对话状态及后台公共组件。",
             "<b>技术难点：</b>以 BBox + Content 双重定位支持跨页、多引用和复杂 PDF；SSE 支持停止生成、重新生成及弱网恢复。",
             "<b>在线项目：</b><link href='https://os.smartbuddy.me' color='#087E8B'><u>https://os.smartbuddy.me</u></link>。"]),
    project("维小智（企业 AI 助手）", "前端 / 全栈", "2024.01 - 2026.01", "Vue3 · TypeScript · Nest.js · SSE · Element UI · MySQL",
            ["<b>项目背景：</b>基于企业自研知识库的智能问答平台，解决前端直连 Java 服务的协议兼容与流式交互问题。",
             "<b>核心职责：</b>开发 AI Chat、后台管理和长列表模块；使用 Nest.js 中间层统一模型协议、鉴权及跨域。",
             "<b>技术成果：</b>Last-Event-ID + 指数退避优化弱网重连；虚拟列表支撑 10000+ 数据，系统稳定运行 2 年无重大故障。"]),
]

story += [section("核心业务与工程项目")]
story += [
    project("催收系统 2.0", "前端负责人", "2024.04 - 2026.02", "React · TypeScript · Rsbuild · Zustand · SWR · ahooks",
            ["<b>项目背景：</b>服务低配置华为云桌面的 PC 催收业务平台，覆盖任务、账务、权限和巡航外呼。",
             "<b>架构与性能：</b>主导整体架构；Rsbuild 替换 Webpack，构建效率提升约 3 倍；虚拟列表、Memo 和缓存优化低内存环境。",
             "<b>业务成果：</b>队列调度 + Zustand 持久化保障跨页面外呼连续执行，落地后预估节省约 450 万/年。"]),
    project("Magic React 组件库", "项目负责人", "2024.06 - 2026.01", "React · TypeScript · Storybook · Ant Design · Vite · Verdaccio",
            ["<b>核心职责：</b>从 0 到 1 设计组件库架构、Storybook 文档与 Verdaccio 私有仓库，规范组件发布流程。",
             "<b>技术难点：</b>通过 alias、双入口和双版本依赖兼容 Ant Design v4/v5，降低存量项目迁移成本。",
             "<b>成果：</b>沉淀 50+ 通用组件，后台需求开发效率提升约 40%。"]),
]
story.append(PageBreak())

# Page 3
story += [section("更多项目经历")]
story += [
    project("维财务", "React Native 跨端开发", "2024.07 - 2026.01", "React Native · Expo · Expo Router · Zustand · TanStack Query",
            ["<b>项目背景：</b>企业移动办公应用，覆盖实时聊天、任务看板、文件上传和消息通知。",
             "<b>核心职责：</b>统一 Web/App 路由、状态和数据缓存，抽离公共业务逻辑；EAS Update 支持热更新。",
             "<b>成果：</b>约 95% 代码跨端复用，开发效率提升约 30%。"]),
    project("贷后策略引擎", "前端负责人", "2022.12 - 2023.12", "Umi · TypeScript · Ant Design · jsMind · Rollup",
            ["<b>项目背景：</b>以思维导图配置复杂贷后策略的可视化平台，降低业务人员配置门槛。",
             "<b>技术难点：</b>深入 jsMind 源码，扩展条件节点、批量复制粘贴和树结构定位；改造 Rollup 打包流程。",
             "<b>性能优化：</b>使用 DocumentFragment 减少 DOM 操作，提升大量节点场景渲染性能。"]),
    project("OA 重构", "前端负责人", "2022.12 - 2023.05", "Umi · TypeScript · Ant Design · Dva",
            ["<b>核心职责：</b>重构 OA 核心模块、公共能力与首页，并接入 AI 办公助手提升员工信息查询效率。",
             "<b>性能成果：</b>通过拆包、Gzip 和核心数据缓存将 LCP 从约 2.5s 降至 1.2s，服务 2000+ 员工。"]),
    project("CMS 微前端平台", "前端开发", "2021.08 - 2022.05", "React · TypeScript · qiankun · Vue · Ant Design",
            ["<b>项目背景：</b>支撑新房、二手房、租房、装修等业务的房产 CMS 微前端平台。",
             "<b>核心职责：</b>参与 qiankun 架构、统一通信与生命周期管理，协调多团队依赖和版本问题。",
             "<b>成果：</b>支持 5+ 子应用独立开发与发布，研发效率提升约 60%。"]),
    project("小区全景项目", "前端开发", "2020.06 - 2021.05", "React · TypeScript · Three.js · Redux",
            ["<b>项目背景：</b>3D 小区全景平台重构，覆盖 PC 与 App 端的地图、指南针、信息面板和工具模块。",
             "<b>技术难点：</b>抽象全景 SDK 能力层、模块化管理 Three.js 场景对象，隔离业务逻辑并复用公共模块。",
             "<b>成果：</b>SDK 被多个项目复用，降低双端差异化开发成本并保持 3D 渲染稳定。"]),
]

story += [section("教育背景")]
edu = Table([[P("普洱学院｜信息管理与信息系统（本科）", job_style), P("2014.09 - 2018.07", meta_style)]],
            colWidths=[doc.width - 42 * mm, 42 * mm], style=TableStyle([
                ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
story += [edu, P("三次获得奖学金 · 省级优秀毕业生", base)]

story += [section("个人特点")]
story += bullets([
    "技术驱动，持续关注 AI 应用、前端工程化和跨端开发，能够快速学习并落地新技术。",
    "重视代码质量、性能和可维护性，具备从 0 到 1 推进项目及跨团队协作经验。",
    "擅长复杂问题定位与方案拆解，能在业务压力下平衡交付效率和系统稳定性。",
])

doc.build(story)
print(OUT)
