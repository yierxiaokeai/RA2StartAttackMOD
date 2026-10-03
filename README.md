# 红警2「开始进攻」MOD

## 功能

- 遭遇战中增加「开始进攻」建筑。玩家建造后，电脑才会组织主动进攻；建筑位于第一页建筑栏最后，售价 100，带独立图标。
- 初始资金滑块范围为 **5,000–500,000**，默认 10,000，每次调整 100。
- 电脑常规进攻队伍的步兵按原编组扩充，**每队步兵合计最多 30 人**，保留原有兵种比例；坦克为原来的 **3 倍**，基洛夫每队 **5 艘**。
- 守家队伍保持原规模；间谍、工程师、谭雅、恐怖分子及运输突袭等偷袭或特种任务队伍不按倍数扩编。
- 电脑基地防御建筑的各难度建造目标数量翻倍。尤里的复仇版启用苏军战斗碉堡驻兵触发，电脑拥有碉堡后可派出原规模的 5 人动员兵驻兵队伍。

原始尤里 AI 的战斗碉堡驻兵触发在全部难度关闭；本 MOD 将其启用，并让触发条件覆盖电脑拥有一座及更多碉堡的情况。驻兵队伍同时最多一支，保持每队 5 人。

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

两套规则已检查建筑注册、资金范围、图标引用、常规进攻步兵上限、守家与偷袭编组原规模、基地防御建筑目标数量，以及识别出的主动进攻触发：尤里版 136 条，原版 89 条。尤里版还检查了碉堡驻兵队伍及触发的难度开关。两个版本的程序修正均通过滑块初始化与实际滑块处理代码的 x86 模拟测试，涵盖 5,000–500,000 的范围、位置设定和读回；排序比较函数也通过模拟测试。防御建筑数量是电脑的建造目标上限，实际数量仍取决于地图空间、资金和战局。真实游戏界面和遭遇战尚需在使用者环境中验证。

可在生成相应版本的包后运行额外模拟测试：

```powershell
python -m pip install -r requirements-test.txt
python install.py --game "D:\Program\Game\RA2MD" --variant YR --build-only
python test_money_slider.py
python install.py --game "D:\Program\Game\RA2" --variant RA2 --build-only
python test_ra2_money_slider.py
```
