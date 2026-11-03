alpha-poke game review -- Windows (x64)
========================================

START
  Unzip first: right-click the downloaded zip -> "Extract All". Running the
  .exe from inside the zip (opened in File Explorer without extracting) does
  not work: it needs the _internal folder beside it.

  Then double-click alpha-poke-review.exe in the extracted folder (File
  Explorer is fine; keep the folder together).

  The first time, Windows may say "Windows protected your PC" (the app is not
  signed): click "More info", then "Run anyway".

  A console window opens, then your browser opens the app's home page
  (http://127.0.0.1:8090/, or the next free port). If the browser does not
  open, open the address shown in the console window.

STOP
  Close the console window.

USE IT
  Paste a Pokemon Showdown replay link of a Gen 9 OU singles game, choose which
  player you were, and start the review. Optionally paste your team
  (Showdown teambuilder -> Export, or a PokePaste link) for exact sets.

  The coach (optional): on the home page, set a language model -- a cloud
  service's address, key and model, or a model you run with Ollama
  (http://localhost:11434/v1, no key). Without it the reviews work the same;
  only the written commentary and the questions are missing.

YOUR DATA
  Reviews and settings are kept in %LOCALAPPDATA%\alpha-poke (they stay when
  you update the app; delete that folder to remove everything).

LICENSES
  The app's code is MIT (LICENSE). The network and belief models are for
  non-commercial research use: the replays they were trained on are public
  games from datasets that state no license. Third-party software:
  THIRD_PARTY_LICENSES.txt.


宝可梦对战复盘 —— Windows（x64）
================================

启动
  先解压：右键下载的 zip → “全部解压缩”。不解压、直接在文件资源管理器里
  打开 zip 双击 .exe 是运行不了的：它需要旁边的 _internal 文件夹。

  然后在解压出来的文件夹里双击 alpha-poke-review.exe（在文件资源管理器里
  双击就行；不要把 .exe 单独拿出来）。

  第一次运行时，Windows 可能提示“Windows 已保护你的电脑”（程序没有数字签名）：
  点“更多信息”，再点“仍要运行”。

  会先打开一个命令行窗口，然后浏览器打开首页
  （http://127.0.0.1:8090/，被占用时换下一个端口）。浏览器没有自动打开的话，
  手动打开命令行窗口里显示的地址。

退出
  关闭命令行窗口。

使用
  粘贴一局 Pokémon Showdown 的 Gen 9 OU 单打回放链接，选择你是哪一位玩家，
  开始复盘。可以再贴上你的队伍（Showdown 队伍编辑器 → Export 导出，或者
  PokéPaste 链接），配置就是精确的。

  教练（可选）：在首页设置语言模型——云端服务的地址、Key 和模型，或者用
  Ollama 在本机部署的模型（http://localhost:11434/v1，不需要 Key）。
  不设置也能正常复盘，只是少了文字点评和问答。

你的数据
  复盘和设置保存在 %LOCALAPPDATA%\alpha-poke（更新程序后仍然保留；
  删掉这个文件夹即可清除全部数据）。

许可证
  程序代码采用 MIT 许可证（LICENSE）。神经网络和信念模型仅供非商业研究使用：
  训练用的回放是公开对局，所在的数据集没有声明许可证。第三方软件的许可证见
  THIRD_PARTY_LICENSES.txt。
