"""评估用的固定议题集。

挑选原则：覆盖不同的决策类型，让不同偏见的大臣都有话说。
每个 case 都给了背景，因为背景会切句进蝴蝶文库 —— 没有背景就测不到检索那条链路。

**这个集合要稳定。** 改议题就等于换了尺子，前后两次 run 不再可比。
真要加，只往后追加，不要改动已有的 case_id 和文案。
"""

CASES = [
    dict(id="quit-job", lang="zh",
         topic="要不要辞职去开一家猫咖",
         context="存款够撑八个月。房东明年涨租百分之十五。同事说猫咖回本要两年。我对猫毛轻微过敏。"),
    dict(id="confess", lang="zh",
         topic="该不该先给她发消息",
         context="上次是我没回。她朋友说她最近在忙论文。我们已经四天没说话了。"),
    dict(id="big-buy", lang="zh",
         topic="要不要把年终奖全买显卡",
         context="奖金三万二。手头那张用了四年。下个月要交房租八千。二手市场最近在跌价。"),
    dict(id="phd", lang="zh",
         topic="三十岁去读博是勇敢还是逃避",
         context="现在月薪两万四。导师说名额还有一个。读完三十五岁。父母希望我结婚。"),
    dict(id="family", lang="zh",
         topic="过年要不要带对象回家",
         context="家里还不知道。我妈去年问过三次。对象说随我。老家那边亲戚话多。"),
    dict(id="absurd", lang="zh",
         topic="该不该给猫办一场生日宴",
         context="它今年三岁。预算两千。邻居养了三只猫。上次办烤肉邻居投诉过噪音。"),
    dict(id="quit-job-en", lang="en",
         topic="Should I quit and open a cat cafe",
         context="Savings cover eight months. Rent goes up fifteen percent next year. "
                 "A colleague says cat cafes take two years to break even."),
]

BY_ID = {c["id"]: c for c in CASES}
