alpha-poke game review -- macOS (Apple silicon)
================================================

START
  Unzip first: double-click the downloaded zip in Finder (it unzips beside
  it). Then, in the alpha-poke-review folder:

  The first time: right-click (or Control-click) start.command, choose Open,
  then Open again. The app is not from the App Store and not notarized, so a
  plain double-click is refused the first time.
  On macOS 15 (Sequoia) and later, if there is no Open button: try once, then
  System Settings -> Privacy & Security -> scroll down -> "Open Anyway".
  After that, double-click start.command.

  A Terminal window opens, then your browser opens the app's home page
  (http://127.0.0.1:8090/, or the next free port). If the browser does not
  open, open the address shown in the Terminal window.

STOP
  Close the Terminal window.

USE IT
  Paste a Pokemon Showdown replay link of a Gen 9 OU singles game, choose which
  player you were, and start the review. Optionally paste your team
  (Showdown teambuilder -> Export, or a PokePaste link) for exact sets.

  The coach (optional): on the home page, set a language model -- a cloud
  service's address, key and model, or a model you run with Ollama
  (http://localhost:11434/v1, no key). Without it the reviews work the same;
  only the written commentary and the questions are missing.

YOUR DATA
  Reviews and settings are kept in ~/Library/Application Support/alpha-poke
  (they stay when you update the app; delete that folder to remove everything).

LICENSES
  The app's code is MIT (LICENSE). The network and belief models are for
  non-commercial research use: the replays they were trained on are public
  games from datasets that state no license. Third-party software:
  THIRD_PARTY_LICENSES.txt.


宝可梦对战复盘 —— macOS（Apple 芯片）
====================================

启动
  先解压：在访达（Finder）里双击下载的 zip，会在旁边解压出文件夹。
  然后在 alpha-poke-review 文件夹里：

  第一次：右键（或按住 Control 点击）start.command，选“打开”，再点“打开”。
  程序不是从 App Store 下载的，也没有经过 Apple 公证，所以第一次直接双击会被拒绝。
  macOS 15（Sequoia）及以后如果没有“打开”按钮：先尝试打开一次，然后到
  系统设置 → 隐私与安全性 → 往下翻 → 点“仍要打开”。
  之后直接双击 start.command 即可。

  会先打开一个终端窗口，然后浏览器打开首页
  （http://127.0.0.1:8090/，被占用时换下一个端口）。浏览器没有自动打开的话，
  手动打开终端窗口里显示的地址。

退出
  关闭终端窗口。

使用
  粘贴一局 Pokémon Showdown 的 Gen 9 OU 单打回放链接，选择你是哪一位玩家，
  开始复盘。可以再贴上你的队伍（Showdown 队伍编辑器 → Export 导出，或者
  PokéPaste 链接），配置就是精确的。

  教练（可选）：在首页设置语言模型——云端服务的地址、Key 和模型，或者用
  Ollama 在本机部署的模型（http://localhost:11434/v1，不需要 Key）。
  不设置也能正常复盘，只是少了文字点评和问答。

你的数据
  复盘和设置保存在 ~/Library/Application Support/alpha-poke（更新程序后仍然
  保留；删掉这个文件夹即可清除全部数据）。

许可证
  程序代码采用 MIT 许可证（LICENSE）。神经网络和信念模型仅供非商业研究使用：
  训练用的回放是公开对局，所在的数据集没有声明许可证。第三方软件的许可证见
  THIRD_PARTY_LICENSES.txt。
