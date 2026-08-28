"""Targeted final-surface repair for an existing academic report job.

This script does not touch translation pairs, case identities, focus spans, or
provenance.  It rebuilds only Chapter 2 prose, Chapter 3 analysis prose,
Chapter 4, front/back matter, validation, and the final template DOCX.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transpraxis import (academic_quality, academic_validator, academic_writer,
                         final_docx, report_template)


CASE_ANALYSES = {
    "seg-c7fc0af0d6626931-0001": (
        "该例中可以核实的修订只有一处：初译在“视觉体制”后保留英文 scopic regime，改译删除括号中的英文，中文术语本身未变。"
        "这一差异说明两版在术语呈现方式上由中英并列变为只保留中文，句面也相应缩短；现有记录却没有保存删除括注时的说明，因而不能把这一结果解释为译者已经确认读者熟悉该术语。"
        "原文后句的 violent blade 隐喻虽提供了段落语境，但不在本次真实改动范围内，本例只支持对括注删减及术语形式连续性的讨论。"
    ),
    "TD-0022": (
        "planetary communities 出现在一条由破折号延伸的定义链中：前半句先建立观看技术、地球环境与人类主体之间“情感性、非工具性”的关系，后半句再把这种关系引向全章的共同体论述。"
        "译文采用“行星共同体”，使 planetary 与全文的“行星性”“行星维度”共享“行星”这一词根，同时以破折号保留解释关系。"
        "若译为“全球共同体”，容易与文中受到区分的 globalism 混同；“星球社区”又会削弱理论概念的抽象层级。因此，“行星共同体”在本段的主要作用是维持概念谱系，并把关系性描述接续到后文议题。"
    ),
    "TD-0072": (
        "引文用 not ... but rather ... 否定“环境是技术形成的既定背景”，转而强调环境与传感技术在具体语境中共同生成。译文以“并非……而是……”保留这一论证转向，并将 take hold and concresce 处理为“扎根并共生凝结”，使抽象的共构关系获得过程性表达。"
        "sensor technologies 译为“传感器技术”，在此指向具体技术装置，与 sensorium 所指的综合感知形态并不相同。该区分让后一句关于技术、自然与人的交织能够承接引文，而不是把装置与感知经验合并为同一概念。"
    ),
    "TD-0028": (
        "句中 at stake 不是孤立的情绪词，它同时关联两条路径：一是审美无人机想象对地球的空中感知，二是政治行动中无人机作为抗议工具的功能。译文用“处于危急关头”选择了较强的风险义，使句子的评价色彩明显化；这种选择与 political activism and intervention 的语境相接，但也比“受到检验”或“成为争论焦点”更具危机感。"
        "aesthetic drone imaginaries 译为“审美无人机想象”，则把 aesthetic 限定为感知与想象层面的修饰语。因而本例既展示评价词的强度选择，也提示此处需要结合上下文判断 at stake 的具体语气。"
    ),
    "TD-0040": (
        "flattening gaze 在这里把无人机的俯视方式写成一种具有主动性的“凝视”，并把视觉上的压平与土地整体性的印象相连。译文用“扁平化凝视”保留名词性隐喻：“扁平化”对应空间深度被压缩，“凝视”则延续观看行为所带的立场。"
        "后续“尽管海浪被边界分隔，但两侧……相同”构成让步关系，使该隐喻不再只指军事控制，而被用于讨论边界之下的相互连通。由此，本段的关键不是证明这种译法产生了特定读者反应，而是说明同一意象如何在当前语境中参与“分隔—整体”之间的论证转换。"
    ),
    "TD-0074": (
        "标题 Volumetric Sensing and Postcarbon Communities 先提出核心概念，随后两个问句把它置于“军事起源是否决定关系”与“能否超越垂直权力”之间。译文以“体积感知”对应 volumetric sensing，并把 or 引出的选择关系处理为“是否……还是……”，保留了标题与问题之间的递进。"
        "“体积”强调三维空间，而“感知”对应 sensing 的过程属性，因此比只写“空间感知”更能与后文 vertical、ground 等空间词形成对照。本例的论证价值在于显示术语并非标签，而是两个对立问题的共同支点。"
    ),
    "TD-0058": (
        "源语以 instead 改写 flatness 的通常含义：扁平化在此不再导向控制，而是与声景、鹿群图案共同构成对地球的互联感知。译文把这一转向置于句首“相反”，并以“这种扁平化”回指前文视觉形态，使对比关系清晰可见。"
        "planetary vision of community 被处理为“行星共同体的愿景”，将 vision 的修饰范围明确落在 community 上；同句中的 sensorium 仍译为“感知域”。这些选择共同保持了“感知形态—共同体想象”的关系，但结论限于该段的语义组织，不等同于对所有扁平化图像作正面评价。"
    ),
    "TD-0020": (
        "It is this ... that I want to trace 是强调结构，焦点落在具有操作性视觉的空中图像之“审美侧面”。译文以“正是这种……审美侧面，我试图……”把焦点前置，随后用“在鲍德温的气球图像以及当代艺术家的审美无人机想象中”交代追溯范围。"
        "这一处理补充了前述术语案例的句法维度：aesthetic drone imaginaries 不只是名词对译，还与 trace 所支配的两个并列对象相连。焦点译文没有收入后句关于“具有制图特征但不完全是地图”的让步，因此本例只承担强调结构与概念落点的辅助说明。"
    ),
    "TD-0015": (
        "此处源文先用 plain 和 level 解释 balloon view，随后以 rather than toward the horizon 限定观看方向，实际上给 flattening gaze 提供了文本内定义。译文把它组织为“向下凝视地球而非朝向地平线的扁平化凝视”，让方向对立直接修饰核心短语。"
        "与例[5]强调土地整体性不同，本例补充的是隐喻的空间来源：地貌失去纵深、对象变得孤立，因而“扁平化”具有可由上下文追溯的视觉依据。“凝视”保留观看主体的主动性，但本段本身不足以推出更广泛的政治效果。"
    ),
    "TD-0073": (
        "multiperspectival sensorium 由 multiperspectival 与 sensorium 组合，后文又立即把它界定为能够把握三维空间的 volumetric sensing。译文用“多视角感知域”保留复合构词关系，其中“感知域”与全文 sensorium 的译法相接，“多视角”则对应观察方向的复数性。"
        "这一选择能把术语与随后 x、y、z 三轴的定义联系起来。不过，同一译句把 volumetric sensing 写成“体积传感”，而其他案例多用“体积感知”，暴露出当前工作稿内部尚未统一的译名。因而本例既支撑“多视角感知域”的概念显化，也明确提示终稿前需统一后一术语。"
    ),
    "TD-0063": (
        "本句把 flattening gaze 放入三组二元对立——原住民/非原住民、自然/技术、古代/现代——之中，并用 not defined by 否定这些对立对共同体的限定。译文保留“扁平化凝视”，又用“并非由……所定义”统摄三个并列项，使术语与否定结构共同服务于行星共同体的非二元论述。"
        "它对例[5]的补充不在于再次证明同一译名，而在于展示该译名换到文化、技术与时间三种对立语境后仍保持相同指称，同时承担新的论证功能。"
    ),
    "TD-0119": (
        "volumetric sensing 在此由一串可感知的动作具体化：节奏、声音、视觉和触觉“拥抱”景观，并同时触及地球深处、表面与大气。译文采用“体积感知”，其中“感知”可以覆盖多种感官通道，“体积”则与深度、表面和大气构成的三维范围对应。"
        "句中的破折号被保留下来说明 synesthetic sensoriality 的内涵，but also 译为“同时又”，使深入与贴近两种方向并置。这个例子因此为术语提供了空间和感官层面的语境证据，而不仅是重复一条词表对应。"
    ),
    "TD-0029": (
        "planetary communities 在本段首先通过否定句被界定：它不应等同于把所有生命同质化为单一世界整体。译文保留“行星共同体”，并把 homogenize 与 one-world totality 分别落实为“同质化”和“单一世界整体”，从而留下概念的限制条件。"
        "不过，当前译文焦点没有覆盖源文随后以 Rather 引出的“变动、悖论、不完整并开放重构”等正面界定，因此本例只能补充术语的否定边界，不能单独支撑关于开放性或他异性的完整结论。若在正文中讨论后一层含义，应回到完整对应译文再作核对。"
    ),
    "TD-0126": (
        "这一材料呈现的不是可供评价的译法，而是译后检查发现的对应异常。原文讨论 environment 作为人与自然相互构成的关系，以及技术如何生成这种纠缠；所配译文却残留大段英文，并转向 Armstrong 将无人机移出军事和工业语境的另一论述。"
        "两者不属于同一局部翻译单位，因此不能据此判断术语或句法策略，更不能把英文残留说成已经修复。它在本章中的作用仅是说明最终检查必须同时核对语言残留与原译文对齐；进入交付稿前仍需人工回到完整片段处理。"
    ),
    "TD-0047": (
        "原文先列举 desert valleys、dry mountains、带有绿意的山丘和干涸河床，随后才说明无人机画面带来的扁平化效果。当前译文焦点从第二层论述开始，完整呈现了“地表和地质构造—扁平化图像—行星视角”的链条，却没有包含开头的地貌列举。"
        "这使本例适合用来检查局部完整性，而不适合作为翻译策略成效的核心证明：若完整目标片段确已省略列举，需判断是焦点截取造成还是译文遗漏；在该判断完成前，只能记录对应范围上的缺口。"
    ),
    "TD-0003": (
        "该原文讨论媒介考古与谱系方法如何反驳无人机技术乐观主义，并转入无人机与气球的谱系关联；当前所配译文却讨论行星主体、全球金融化和资本主义同质化。两段主题、谓词和关键术语均无法建立局部对应。"
        "因此，这里没有可以成立的“原文—译文”策略分析，异常本身才是有用信息：案例装配若只验证文本来自同一项目，而不核对语义单位，就可能把两个合法片段错误配对。本例保留为译后对齐检查的反例，不能进入研究问题的核心证据。"
    ),
    "TD-0124": (
        "两句源文形成双层对立。第一句以 Although 承认无人机属于空中勘测技术，同时指出它可以抵消疏离并把景观建筑师重新置于地面；第二句再用 not by virtue of ... but rather through ... 排除“垂直特征”，引出“体积感知”。"
        "译文分别使用“尽管……但……”和“并非……而是……”，没有合并两层让步与选择关系。代词 It does so 译为“它……实现这一点”，回指前句的抵消与重新定位。由此，长句处理的关键是保留论证层级，而非简单增加连接词；当前对照能够直接显示这两组逻辑关系在汉语中的落点。"
    ),
    "TD-0117": (
        "主句说蒙太奇的多视角性 undermines 垂直视觉体制，which 从句却说明这种视觉体制因悬停拍摄和斯坦尼康式视角而 enhanced，语义上形成“削弱—强化”的张力。译文不沿用英语关系代词，而重复先行词“这种视觉体制”，再以“又因……得到强化”引出原因。"
        "这种名词回指消除了 which 的指向歧义，同时保留两个相反谓词的对照。焦点译文没有收入下一句对斯坦尼康视角“不同寻常”的解释，所以本例的核心只在关系从句的展开和先行词复现。"
    ),
    "TD-0095": (
        "焦点中的主要句子由两个并列主语构成：多光谱图像的视觉美学，以及描述这些图像的措辞选择；since 从句再解释二者为何值得关注。译文沿用“……以及……”并列两个名词短语，以“因为”引出理由，把 neutral 加引号译为“中立”，保留作者对技术科学语言并非价值中性的质疑。"
        "句首“尽管如此”承接前一句工程师和生物学家不会把植物话语与无人机战争修辞相比的背景，因此该例补充的是跨句转折、并列主语与原因从句的组合，而不是一般性的长句拆分。"
    ),
    "TD-0088": (
        "through which 的先行内容是无人机促成的“环境可编程性”，若逐字译成“通过其”，容易让代词在无人机、技术和环境之间游移。译文改用“通过该技术”，把关系从句展开为独立分句，并在后半句列出“生成环境”和“配置技术地理学”两个并列动作。"
        "这种处理保留了主句先提出核心概念、从句再说明运行方式的信息顺序。它没有处理焦点后两句关于多光谱成像的定义，因此只为关系从句的指向与展开提供辅助证据。"
    ),
    "TD-0102": (
        "该句包含多层嵌套：Steinmetz states 引出陈述，although 建立生涯初期与后来认识之间的让步，that 引入直接引语，because 和 if 又在引语内部形成原因与条件。译文依次使用“表示—尽管……但……—因为—如果”，把四层关系按原有顺序展开。"
        "“不能继续以今天的速度消耗资源”被置于条件目标“为后代留下宜居星球”之前，保持 because 所解释的限制逻辑。此例说明复杂句的可读结构来自连接关系的分层落实，而不是把所有从句一律切成短句。"
    ),
    "TD-0114": (
        "源语先断言 volumetric sensing 在下一节至关重要，再以 as 解释原因；artworks 后的 that 从句与 deeply sensing 分词结构继续限定这些艺术作品。译文用“因为”明确 as 的因果读法，并以“那些……的艺术作品”承接关系从句。"
        "后半部“深入感知地表之下及地质时间尺度的地球”仍可能让“地质时间尺度”与“地球”的修饰关系显得拥挤，说明显化连接词并不能自动解决所有附着问题。该例补充了原因从句与多重后置修饰同时出现时的处理边界。"
    ),
    "TD-0077": (
        "分号连接两个相对独立的命题：概念的使用范围从地球科学扩展出去；人文学科据此讨论人类主体相对于地球、可持续性与自然环境开发的角色和立场。译文保留分号，使“范围扩展”与“学科运用”不被压成同一层修饰。"
        "后半句把 with regard to 后的三个对象集中置于“在……方面”结构中，维持列表关系，但“地球、其可持续性及自然环境开发”之间仍需依靠语义辨认层级。它说明标点可以保存宏观并列，细部名词关系仍需在终稿中核查。"
    ),
    "TD-0108": (
        "主句把“相互关联的空间理念”与作者拓展地球无人机感官调色板的愿望相连，as it allows me ... 再解释这种理念为何有用，that go beyond ... 则限定 aerial space formations。译文以“因为它使我能够”展开 as 从句，并把“超越视觉体制”置于“空中空间形成”之前。"
        "信息顺序仍是理念—作者目的—可描述的空间形态，但代词“它”需要读者回指前面的“空间理念”。因此本例补充的是因果从句和嵌套定语的线性安排，同时保留了一个需要结合上文消解的代词指向。"
    ),
}


CHAPTER_2 = """### 2.1 项目简介

本项目的翻译对象为 Kathrin Maurer 所著《The Sensorium Of The Drone And Communities》第三部分，语言方向为英语译简体中文。源文属于媒体研究与环境人文学交叉领域的学术专著章节，讨论无人机视觉、行星性、体积感知以及人类—技术—环境共同体。PDF 经解析后形成 138 个可处理片段，138 个片段均保存了对应译文。项目范围只覆盖当前提取部分，不代表整部专著已经完成翻译。截至报告整理时，译文仍为工作稿，尚未完成最终交付确认。

### 2.2 翻译流程

翻译流程分为译前准备、翻译实施和译后管理三个阶段。以下说明均来自当前保存的文档与操作记录，不把自动检查写成人工审校，也不据工具记录反推未被记录的翻译方式。

#### 2.2.1 译前准备

译前首先对源 PDF 进行文本解析和片段化处理，并建立文档画像。文本分析显示，源文采用正式学术书面语，理论阐释、艺术作品评论和技术描述相互交织；长句中常见定语从句、插入语、并列链条和多层逻辑关系。术语准备阶段整理了 39 项主要术语记录，重点关注 planetarity、scopic regime、sensorium、volumetric sensing 等跨学科概念及其上下文关系。与此同时，项目保存了保留引文结构、注释编号和核心理论术语，避免口语化，并使长句层级清晰等风格约束。当前没有可核验的外部术语文献，因此术语判断以本文内部一致性为主，不声称属于学界通行译法。

#### 2.2.2 翻译过程

翻译阶段按片段保存原文、初始译文和当前译文，共形成 138 组记录，并累计保存 107 条术语约束。处理复杂句时，重点核对让步、因果、对比、并列和回指关系在汉语中的落点；处理概念词时，则结合相邻定义和全文词根关系检查译名是否前后一致。翻译记忆功能处于启用状态，但当前记录中没有观察到翻译记忆库复用；这一记录不能说明机器翻译或大语言模型是否参与，也不能据此判断效率或译文质量。

#### 2.2.3 译后管理

译后阶段对 84 个片段形成自动检查记录，共记录 56 条待核查事项。保存的流程记录显示共有 5 次人工操作，138 个片段中只有 1 个片段出现可核实的实质性初译—终译变化，因此本报告将大多数案例作为“当前译法为何在该语境中成立”的翻译决策分析，而不虚构修订历史。译后还汇总了主要术语对照，并对源语残留、内容遗漏、局部对齐和术语一致性进行检查。部分问题仍待人工复核，尤其是原译文对应异常和英文残留；所以本阶段的结果是形成可继续修订的工作稿，而不是确认译文已经满足最终质量要求。
"""


CHAPTER_4 = """### 4.1 研究问题回应

#### 4.1.1 RQ1：长句论证链与信息结构

<!--rq:RQ1--><!--claim:C1-->
例[17]和例[18]构成本问题的主要依据。前者显示，同一语段中的让步关系与“并非……而是……”对比需要分层呈现；后者则通过复现先行词“这种视觉体制”，把英语 which 从句展开为指向明确的汉语分句。例[19]至例[24]进一步表明，并列主语、原因从句、条件从句、分号连接和嵌套定语并不适合用单一的“拆句”原则处理。当前译文较常采用的做法是先识别命题之间的逻辑关系，再决定使用连接词、名词回指、标点或语序调整。这里能够得到的有限结论是：对于本项目中的复杂句，信息层级的可辨认性比形式上的句数对应更重要；个别译句仍存在修饰附着或代词回指需要复核的情况。

#### 4.1.2 RQ2：概念术语的一致处理

<!--rq:RQ2--><!--claim:C2-->
术语案例显示，译名是否合适需要放在概念网络中判断。“多视角感知域”保留 multiperspectival 与 sensorium 的构词关系，“行星共同体”与“行星性”“行星维度”共享词根，“体积感知”则与深度、地表和大气等三维语境相互解释。与此同时，例[10]中“体积传感”与其他位置的“体积感知”并存，说明词根一致并不等于全篇术语已经统一；例[13]也只能支持“行星共同体”的否定性边界，不能脱离缺失的后续译文概括完整定义。因此，对本项目而言，可靠的术语处理包括稳定核心词根、核对相邻定义、区分技术装置与感知形态，并在交付前清理局部变体。

#### 4.1.3 RQ3：隐喻、评价色彩与论证功能

<!--rq:RQ3--><!--claim:C3-->
修辞案例的共同点不是简单保留某个形象词，而是让意象继续参与段落论证。“扁平化凝视”在例[5]中连接边界与土地整体性，在例[9]中则由俯视方向和空间深度的消失获得具体含义；同一表达在不同语境中的论证任务并不相同。例[6]的连续问句保留“军事起源—超越垂直权力”的选择关系，例[7]借句首“相反”把扁平化从控制性视觉转向互联感知，例[4]则暴露 at stake 译为“处于危急关头”时的语气强度选择。由这些文本对照可以回答：本项目主要通过保留核心意象、显化对立关系并校准评价词强度来再现修辞功能；这一结论只适用于所分析语段，不能替代读者反应研究。

### 4.2 主要策略与实践经验

本次实践形成了三项相互配合的处理思路。复杂句先划分命题层级，再选择连接词、回指名词和标点；概念词先确认局部定义与全文词根关系，再决定译名；隐喻和评价表达则同时核对字面形象、语气强度及其在段落中的论证位置。案例分析还显示，译后质量检查不能与翻译策略混为一谈。例[14]至例[16]所呈现的英文残留、内容范围缺口和原译文错配，只能说明需要复核的质量问题，不能被包装成成功译法。将这类材料单列，有助于把“为什么这样译”的文本分析与“当前稿件哪里仍有问题”的流程管理区分开来。

### 4.3 局限与后续改进

本报告的主要局限有三点。第一，138 个片段中只有 1 个案例保存了可核实的实质修订，其他案例主要支持对当前译法的文本分析，不能用于重建译者未记录的动机。第二，当前尚未建立可核验的翻译理论与术语文献体系，因此本文可以讨论文本内部的一致性和概念关系，却不能把译名断言为通行、最佳或具有普遍效力。第三，三个质量检查案例仍有待人工核对，其中两例存在明显的原译文对齐问题。后续应优先完成这些片段的人工复核，统一“体积感知”等核心译名，并补充经过核验的句法、术语与隐喻研究文献；在获得新的修订记录或读者反馈后，再检验本报告提出的有限结论是否能够扩展。
"""


DIFFICULTY_TEXT = {
    "3.2.1": "修辞难点集中在意象、评价强度和逻辑对立的共同作用。flattening gaze、at stake 以及围绕军事性与行星共同体的问句，都不是脱离语境即可确定的词义问题；译文既要保留可追踪的语言形式，也要判断它在当前段落中推进了何种立场。",
    "3.2.2": "术语难点来自概念之间的连续关系。sensorium、volumetric sensing、planetarity 与 planetary communities 既有词根联系，也分别指向感知形态、空间维度和共同体想象。孤立查词无法解决这些区别，必须结合相邻定义和全文用例。",
    "3.2.3": "质量检查材料揭示的是工作稿中的残留源语、内容范围缺口和原译文对齐问题。这些现象可以说明译后管理需要核对什么，却不能自动转化为翻译策略，也不能在没有人工确认时写成已经修复的错误。",
    "3.2.4": "长句难点主要表现为让步与对比叠加、关系从句的先行词回指、并列主语、原因与条件从句嵌套，以及后置修饰的附着范围。处理重点是辨认各命题的层级和连接方向，而不是按固定长度机械拆句。",
}


STRATEGY_INTROS = {
    "3.3.1": "本节讨论隐喻形象、评价词强度和对立结构如何共同进入译文。核心案例分别处理行星共同体的关系性定义、环境与技术的共构、at stake 的评价选择、扁平化凝视的语境变化以及连续问句的论证作用；两个补充案例进一步说明强调结构和隐喻空间来源。",
    "3.3.2": "本节从构词关系、文本内定义和相邻概念的区别考察术语选择。案例并不把现有译名称为外部通行方案，而是检查“多视角感知域”“扁平化凝视”“体积感知”和“行星共同体”在当前语料中是否保持可解释的联系，并指出仍待统一之处。",
    "3.3.3": "以下三例属于译后质量检查的辅助材料，而非翻译策略成功案例。它们分别呈现英文残留并错配、局部内容范围缺口以及原译文完全不对应三种情况，用于说明交付前需要怎样核对工作稿；这些案例不承担 RQ1—RQ3 的核心论证。",
    "3.3.4": "本节依据具体句法关系讨论信息重组。两个核心案例分别处理双层让步/对比与关系从句回指；其余案例补充并列主语、关系从句展开、条件嵌套、分号并列和多重后置修饰，借此观察不同结构需要的汉语组织手段。",
}


GROUP_SUMMARIES = [
    "以上案例表明，修辞传递的判断单位应是意象、评价词和段落论证之间的具体关系。同一“扁平化”在控制、整体性和互联感知语境中承担不同功能，译文因而需要保留形象的连续性，同时避免把一个语段的作用推广为普遍效果。",
    "本组案例共同说明，术语一致性既包括稳定的词根对应，也包括概念边界和局部定义。现有译文已经形成若干可追踪的对应，但“体积传感/体积感知”等变体仍须在最终交付前统一，缺失对应的焦点也不能用于扩展术语结论。",
    "三例最终保留在质量控制小节，数量为 3。它们增加的证据维度分别是源语残留、局部遗漏风险和语义错配；由于没有完成相应人工修订，它们只说明检查对象和未决状态，不证明翻译策略有效。",
    "本组案例显示，句法调整应针对真实关系选择手段：对比可用成对连接，关系从句可用名词回指展开，并列可借助标点维持层级，原因与条件则需避免彼此遮蔽。部分译句的附着与回指仍有改善空间，这也是当前策略的适用边界。",
]


def _stable(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _replace_case_analyses(content: str) -> str:
    updated = content
    for case_id, analysis in CASE_ANALYSES.items():
        marker = f"<!--case:{case_id}-->"
        start = updated.find(marker)
        if start < 0:
            raise ValueError(f"missing case marker: {case_id}")
        next_candidates = [value for value in (
            updated.find("\n**例[", start + len(marker)),
            updated.find("\n**本组小结**", start + len(marker)),
            updated.find("\n#### ", start + len(marker)),
        ) if value >= 0]
        end = min(next_candidates) if next_candidates else len(updated)
        block = updated[start:end]
        replaced, count = re.subn(
            r"(?m)^\*\*分析\*\*[：:]\s*.*$", f"**分析**：{analysis}", block, count=1)
        if count != 1:
            raise ValueError(f"case analysis line missing: {case_id}")
        updated = updated[:start] + replaced + updated[end:]
    return updated


def _replace_subsection_preface(content: str, heading_id: str, text: str) -> str:
    pattern = re.compile(
        rf"(?ms)(^####\s+{re.escape(heading_id)}\s+[^\n]+\n\n).*?(?=\*\*例\[|^####\s+)")
    replaced, count = pattern.subn(rf"\1{text}\n\n", content, count=1)
    if count != 1:
        raise ValueError(f"subsection preface missing: {heading_id}")
    return replaced


def _repair_chapter_3(content: str) -> str:
    updated = _replace_case_analyses(content)
    for heading_id, text in DIFFICULTY_TEXT.items():
        pattern = re.compile(
            rf"(?ms)(^####\s+{re.escape(heading_id)}\s+[^\n]+\n\n).*?(?=^####\s+|^###\s+)")
        updated, count = pattern.subn(rf"\1{text}\n\n", updated, count=1)
        if count != 1:
            raise ValueError(f"difficulty subsection missing: {heading_id}")
    updated = updated.replace(
        "#### 3.3.3 审校证据驱动的质量诊断",
        "#### 3.3.3 译后质量检查与问题定位")
    for heading_id, text in STRATEGY_INTROS.items():
        updated = _replace_subsection_preface(updated, heading_id, text)
    summary_pattern = re.compile(r"(?m)^\*\*本组小结\*\*[：:].*$")
    iterator = iter(GROUP_SUMMARIES)
    updated, count = summary_pattern.subn(lambda _match: f"**本组小结**：{next(iterator)}", updated)
    if count != len(GROUP_SUMMARIES):
        raise ValueError(f"expected {len(GROUP_SUMMARIES)} group summaries, found {count}")
    return updated


def _save_json(path: Path, value: Dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def repair(job_id: str, output_name: str) -> Dict[str, Any]:
    artifact_dir = Path("outputs") / job_id
    state = json.loads((artifact_dir / "state.json").read_text(encoding="utf-8"))
    pair_hash_before = _stable(state.get("pairs") or [])
    old_docx = (artifact_dir / output_name).read_bytes()
    prior_audit_path = artifact_dir / "final-report-integrity-audit.json"
    prior_audit = json.loads(prior_audit_path.read_text(encoding="utf-8")) \
        if prior_audit_path.is_file() else {}

    research = academic_writer._read_artifact(artifact_dir / "research-model.json")
    evidence = academic_writer._read_artifact(artifact_dir / "academic-evidence.json")
    argument = academic_writer._read_artifact(artifact_dir / "argument-plan.json")
    selected = academic_writer._read_artifact(artifact_dir / "selected-cases.json")
    outline = academic_writer._read_artifact(artifact_dir / "academic-outline.json")
    sections_artifact = academic_writer._read_artifact(artifact_dir / "academic-sections.json")
    plans = academic_writer._read_artifact(artifact_dir / "case-analysis-plans.json")
    literature_sources = academic_writer._read_artifact(artifact_dir / "literature-sources.json")
    literature_evidence = academic_writer._read_artifact(artifact_dir / "literature-evidence.jsonl")
    literature_claims = academic_writer._read_artifact(artifact_dir / "literature-claims.jsonl")
    synthetic = academic_writer._read_artifact(artifact_dir / "synthetic-case-validation.jsonl")
    template_contract = academic_writer._read_artifact(artifact_dir / "template-contract.json")
    old_report = academic_writer._read_artifact(artifact_dir / "academic-report.json")
    before_surface = final_docx.validate_final_docx(old_docx, old_report)

    sections = [dict(item) for item in sections_artifact.get("sections") or []]
    for item in sections:
        section_id = str(item.get("section_id") or "")
        if section_id == "2":
            item["content"] = CHAPTER_2.strip()
        elif section_id == "3":
            item["content"] = _repair_chapter_3(str(item.get("content") or ""))
        elif section_id == "4":
            item["content"] = CHAPTER_4.strip()
        item["summary"] = re.sub(r"<!--.*?-->", "", item.get("content") or "")[:240]

    report_md = academic_writer._compose_report(sections)
    report_md = academic_writer.finalize_report_tokens(report_md, evidence, selected, outline)
    matter = academic_writer.build_report_matter(
        research, evidence, selected, template_contract, literature_sources)
    report = academic_writer.build_report_artifact(
        report_md, sections, outline, research.get("report_constraints") or {},
        matter, selected, evidence, plans)
    validation = academic_validator.validate_academic_report(
        report_md, evidence, research, argument, selected, outline,
        literature_sources, literature_evidence, literature_claims,
        synthetic_artifact=synthetic, template_contract=template_contract,
        report_artifact=report)
    quality = academic_quality.evaluate_quality(
        research, argument, selected, outline, sections, evidence,
        literature_sources, literature_evidence, literature_claims, validation,
        lambda *_args, **_kwargs: "", "", "", "", plans)
    quality["evaluation_mode"] = "deterministic_only_final_integrity_audit"
    quality["content_hash"] = _stable({
        key: value for key, value in quality.items() if key != "content_hash"})
    report.update(
        report_status="literature_required",
        literature_status="literature_required",
        validation_status=validation.get("status"),
        quality_status="review_required",
        template_compliance=(validation.get("template_compliance") or {}).get("status"),
    )
    report["content_hash"] = _stable({key: value for key, value in report.items()
                                      if key != "content_hash"})

    template_bytes = (artifact_dir / "report-template.docx").read_bytes()
    rendered = report_template.render_report_docx(report, template_bytes, template_contract).getvalue()
    after_surface = final_docx.validate_final_docx(rendered, report)
    if after_surface.get("status") == "fail":
        raise RuntimeError("final DOCX validation failed: " + json.dumps(
            after_surface.get("issues") or [], ensure_ascii=False))

    section_payload = {"schema_version": academic_writer.VERSIONS["writer_version"],
                       "sections": sections}
    section_payload["content_hash"] = _stable(section_payload["sections"])
    _save_json(artifact_dir / "academic-sections.json", section_payload)
    _save_json(artifact_dir / "academic-report.json", report)
    _save_json(artifact_dir / "academic-validation.json", validation)
    _save_json(artifact_dir / "academic-quality-evaluation.json", quality)
    _save_json(artifact_dir / "final-docx-validation.json", after_surface)
    (artifact_dir / "academic-quality-report.md").write_text(
        academic_quality.render_quality_report(quality), encoding="utf-8")
    (artifact_dir / "academic-quality-findings.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True)
                  for item in quality.get("findings") or []) + "\n",
        encoding="utf-8")
    (artifact_dir / "report-final.md").write_text(report_md, encoding="utf-8")
    (artifact_dir / output_name).write_bytes(rendered)

    state["p3_md"] = report_md
    state["p3_sections"] = [[item.get("title"), item.get("content")] for item in sections]
    state["p3_done"] = True
    state["report_status"] = "literature_required"
    academic_state = dict(state.get("academic_state") or {})
    academic_state.update(
        status="review_required", quality_status="review_required",
        report_status="literature_required", current_stage="review_required")
    state["academic_state"] = academic_state
    pair_hash_after = _stable(state.get("pairs") or [])
    if pair_hash_before != pair_hash_after:
        raise RuntimeError("translation pair hash changed during final-surface repair")
    _save_json(artifact_dir / "state.json", state)

    audit = {
        "schema_version": "final-report-integrity-audit-v1",
        "job_id": job_id,
        "scope": ["chapter_2", "chapter_3_analysis_prose", "chapter_4",
                  "abstracts", "toc", "back_matter", "final_docx_validation"],
        "preserved": {
            "translation_pair_count": len(state.get("pairs") or []),
            "translation_pair_hash_before": pair_hash_before,
            "translation_pair_hash_after": pair_hash_after,
            "selected_case_ids": [item.get("case_id") for item in selected.get("cases") or []],
            "selected_case_count": len(selected.get("cases") or []),
        },
        "constraint_trace": {
            "chapter_4_artifact_chars_before": len(str(next(
                (item.get("content") for item in old_report.get("sections") or []
                 if str(item.get("section_id")) == "4"), ""))),
            "chapter_4_markdown_present_before": "## 4 总结与反思" in str(state.get("p3_md") or ""),
            "first_loss": "report_template.render_report_docx dynamic subsection parent anchor",
            "toc_root_cause": "template Word TOC field retained a stale cached result",
        },
        "before": prior_audit.get("before") or before_surface,
        "after": after_surface,
        "chapter_2_chars": len(CHAPTER_2),
        "chapter_4_chars": len(CHAPTER_4),
        "qa_supporting_cases": ["TD-0126", "TD-0047", "TD-0003"],
        "qa_location": "3.3.3 译后质量检查与问题定位",
        "literature_status": "literature_required",
        "quality_refresh": {
            "evaluation_mode": quality["evaluation_mode"],
            "selected_cases": quality["metrics"]["evidence_utilization"][
                "selected_case_count"],
            "cases_used": quality["metrics"]["evidence_utilization"]["cases_used"],
            "high_value_unused_cases": quality["metrics"]["evidence_utilization"][
                "high_value_unused_cases"],
        },
        "output": output_name,
    }
    audit["content_hash"] = _stable(audit)
    _save_json(artifact_dir / "final-report-integrity-audit.json", audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--output", default="academic-report-semantic-repaired.docx")
    args = parser.parse_args()
    result = repair(args.job_id, args.output)
    print(json.dumps({
        "job_id": result["job_id"],
        "pair_hash": result["preserved"]["translation_pair_hash_after"],
        "docx_status": result["after"]["status"],
        "docx_summary": result["after"]["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
