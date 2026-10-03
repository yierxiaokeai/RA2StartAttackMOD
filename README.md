# 红警2「开始进攻」MOD

遭遇战中增加「开始进攻」建筑。玩家建造它后，电脑的普通主动进攻队伍才会开始组织。建筑固定在第一页建筑栏最后，使用专门绘制的红色按钮图标。建筑售价 100，地图模型沿用盟军电厂。

初始资金滑块最低 **5,000**，最高 **500,000**，默认 10,000，每次调整 100。两个版本分别修正了自定义滑块的范围读取；其他滑块沿用原来的处理。

电脑主动进攻队伍的步兵数量调整为原来的 **4 倍**，坦克调整为 **3 倍**，基洛夫编组统一为每队 **5 艘**。需要登载步兵的队伍同步增加运输载具，保持载客能力。守家队伍各单位数量翻倍；电脑基地防御建筑的各难度建造目标数量翻倍。受游戏自身 `BuildLimit=1` 限制的尤里版谭雅和尤里 X 仍保留原队伍数量，避免队伍无法组建。

## 安装

在 Windows 的 PowerShell 中进入本仓库，安装依赖并指定自己的游戏目录：

```powershell
python -m pip install -r requirements.txt
python install.py --game "D:\Program\Game\RA2MD" --variant YR
```

原版红警2使用已检查的 1.08 程序，命令示例：

```powershell
python install.py --game "D:\Program\Game\RA2" --variant RA2
```

可先加 `--build-only`，只生成补丁包到 `_build/安装文件/`，不修改游戏。安装程序只检查正在安装的那个版本；目标游戏正在运行时会停止安装并保留已生成的包。

游戏目录内的 `StartAttackMOD/管理MOD.ps1` 用于切换：

```powershell
pwsh -NoProfile -File "D:\Program\Game\RA2MD\StartAttackMOD\管理MOD.ps1" -Action Disable -Variant YR -GameDirectory "D:\Program\Game\RA2MD"
pwsh -NoProfile -File "D:\Program\Game\RA2MD\StartAttackMOD\管理MOD.ps1" -Action Enable -Variant YR -GameDirectory "D:\Program\Game\RA2MD"
```

脚本安装时先保存被替换的原文件；停用时还原。若上次遭遇战资金低于 5,000 或高于 500,000，安装程序会保存原 `RA2MD.INI`，并将该值设回默认的 10,000。

## 两个版本的范围

尤里的复仇版使用本地 `gamemd.exe` **1.11**；原版红警2使用本地 `game.exe` **1.08**。两版各有独立的滑块与建筑排序修正。构建器检查对应程序的指令后才生成修正程序；版本不匹配时会停止。

普通电脑进攻由 AITrigger 条件控制：它当前选定的敌方需要拥有「开始进攻」建筑。出售或摧毁建筑会阻止后续新进攻队伍，已经派出的队伍会继续行动。多电脑自由混战中，各电脑会按自己当前选定的敌方分别判断；地图自带的独立脚本进攻可能继续发生。请用新开遭遇战测试。

## 补丁内容与验证

仓库只保存构建脚本和自绘图标。安装程序从你本机的 `ra2.mix`、`ra2md.mix`、语言资源和原游戏程序读取基础文件，在 `_build/` 生成完整补丁，再安装到游戏目录；仓库不上传游戏原始程序、原始图形或完整规则文件。

两套规则已检查建筑注册、资金范围、图标引用、进攻及守家编组、基地防御建筑目标数量，以及识别出的主动进攻触发：尤里版 136 条，原版 89 条。两个版本的程序修正均通过滑块初始化与实际滑块处理代码的 x86 模拟测试，涵盖 5,000–500,000 的范围、位置设定和读回；排序比较函数也通过模拟测试。防御建筑数量是电脑的建造目标上限，实际数量仍取决于地图空间、资金和战局。真实游戏界面和遭遇战尚需在使用者环境中验证。

可在生成相应版本的包后运行额外模拟测试：

```powershell
python -m pip install -r requirements-test.txt
python install.py --game "D:\Program\Game\RA2MD" --variant YR --build-only
python test_money_slider.py
python install.py --game "D:\Program\Game\RA2" --variant RA2 --build-only
python test_ra2_money_slider.py
```

图标原画：[assets/开始进攻-原画.png](assets/开始进攻-原画.png)。游戏图标：[assets/sgsticon.shp](assets/sgsticon.shp)。使用内置 imagegen 绘制，提示词见 [assets/绘制说明.md](assets/绘制说明.md)。

图标提示词：复古军事 RTS 侧栏图标，坚固的橄榄绿进攻指挥台、醒目的红色启动按钮、显示前进箭头的绿色雷达屏，底部准确写「开始进攻」，强对比，缩到 60×48 仍可辨认。
