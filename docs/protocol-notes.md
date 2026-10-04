# 超星学习通协议要点

> 本文档记录 cxauto 实现所依据的超星服务端协议细节，供后续维护与适配改版使用。
> 协议要点参考自 Samueli924/chaoxing 与 RainySY/chaoxing-xuexitong-autoflush 的实现。

## 1. 登录

- 端点：`POST https://passport2.chaoxing.com/fanyalogin`
- 密码加密：**AES-CBC**（不是 RSA），key 与 IV 均为前端硬编码的 `u2oh6Vu^HWe4_AES`，PKCS7 填充后 Base64；**用户名与密码都加密**
- 表单：`fid=-1`（不指定单位，自动解析）、`uname`、`password`（均加密）、`refer`、`t=true`、`forbidotherlogin=0`、`validate=""`、`doubleFactorLogin=0`、`independentId=0`
- 成功：响应 JSON `status: true`；失败读 `msg2`
- 登录后关键 Cookie：**`_uid`（用户 id，参与 enc 计算与 userid 参数）**、`fid`（单位 id，用于视频元信息接口）、`_d`、`vc3`

## 2. 课程与章节

### 课程列表

`POST https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata`
表单 `{courseType:1, courseFolderId:0, query:"", superstarClass:0}`，
**必须带 Referer** `https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=...`，否则返回空。

返回 HTML 片段：`div.course` 中 `input[name=courseId]`、`input[name=clazzId]` 取 id；`cpi` 从课程链接 href 正则 `cpi=(\d+)` 提取（**后续所有接口必备**）；含 `not-open-tip` 的为未开放课程。

课程可能归入文件夹：`visit/interaction` 页面解析 `ul.file-list>li` 的 `fileid`，再按 folderId 重复 courselistdata。

### 章节列表

`GET /mooc2-ans/mycourse/studentcourse?courseid=&clazzid=&cpi=&ut=s`
解析 `div.chapter_unit` 下的 `div#cur\d+`：id 去 `cur` 前缀即 **knowledgeid**；`input.knowledgeJobCount` 为任务点数；`span.bntHoverTips` 文本含「解锁/已完成」标记状态。

### 任务卡片

`GET https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid=&courseid=&knowledgeid=&ut=s&cpi=&v=2025-0424-1038-3&mooc2=1&num=N`

**num 必须 0~6 穷举**——一个章节可能有多张卡片，少一张会导致任务不完整。页面内嵌 `mArg = {...};`：

- `mArg.defaults`：`ktoken, mtEnc, reportTimeInterval(默认60), defenc, cardid, cpi, qnenc, knowledgeid, reportUrl`
- `mArg.attachments`：任务点数组，关键字段：
  - `type`：`video / document / workid / read`；直播按 property 中 `liveid/streamName/vdoid` 识别
  - `jobid`、`objectId`（文档类在 `property.objectid`）、`enc`、`jtoken`、`otherInfo`（形如 `nodeId_12345-cpi_82274641-rt_1d`）
  - `playTime`（毫秒，服务端记录的断点）、`isPassed: true` 可跳过
  - **注意**：otherInfo 是否携带 courseId 会改变服务端的 URL 处理，统一截掉 `&` 之后内容

## 3. 视频刷课（核心）

### 元信息

`GET https://mooc1.chaoxing.com/ananas/status/{objectid}?k={fid}&flag=normal`
返回 `{status:"success", dtoken, duration(秒), crc, key, playTime(毫秒)}`；**dtoken 是日志上报 URL 的路径段**。Referer：`https://mooc1.chaoxing.com/ananas/modules/video/index.html?...`

### 日志上报

`GET https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/{cpi}/{dtoken}`，参数：

```
clazzId, playingTime, duration, clipTime=0_{duration}, objectId, otherInfo,
courseId, jobid, userid, isdrag, view=pc, enc, dtype=Video|Audio, rt, _t
```

- `isdrag`：0=普通心跳，4=结束上报。**开局先发一次 `isdrag=4, playingTime=duration` 试探秒过**，返回 `isPassed:true` 即完成——这是最主要的提速手段
- `rt`：优先 `property.rt`；从 otherInfo 正则 `-rt_([0-9a-z])` 提取，`d` 映射 `0.9`
- 视频与音频分别用不同播放器 Referer；部分任务需换 `dtype=Audio` 才能通过

### enc 算法

```
enc = MD5( "[clazzId][userid][jobid][objectId][playingTime*1000][d_yHJ!$pdA~5][duration*1000][0_duration]" )
```

八段方括号拼接后整体 MD5，32 位小写 hex；盐值 `d_yHJ!$pdA~5` 为前端 JS 硬编码。clipTime 在前端本是区间数组 `[0, duration]`，序列化即 `0_{duration}`。

### 节律与风控

- 心跳间隔随机 30~90s（官方 `reportTimeInterval` 默认 60s 的随机化版本），每次上报后重新随机
- 倍速 = 视频时间流逝倍率，**必须 ≤2.0**
- 视频日志接口对频率极敏感，上报间隔 ≥2s 并加随机抖动
- 403/响应含「验证码」：暂停 2~4s → 过验证码（`GET /processVerifyPng.ac?t=` 取图 + `GET /html/processVerify.ac?ucode=&app=0` 提交，**302 即成功**）→ 重新拉 `ananas/status` 取新 dtoken 后续播

## 4. 文档与阅读

新协议下均为**一次性 jtoken 校验请求**，无需模拟阅读时长：

- 文档：`GET /ananas/job/document?jobid=&knowledgeid=&courseid=&clazzid=&jtoken=&_dc={ms}`
- 阅读：`GET /ananas/job/readv2?jobid=&knowledgeid=&courseid=&clazzid=&jtoken=`
- `knowledgeid` 从 otherInfo 正则 `nodeId_(.*?)-` 提取；200 即完成

## 5. 测验（workid，未实现）

- 取题：`GET /mooc-ans/api/work?api=1&workId=&jobid=&knowledgeid=&ktoken=&cpi=&ut=s&enc=&mooc2=1&courseid=...`
- 题目页面存在**字体反爬**：`<style id="cxSecretStyle">` 内嵌 base64 TTF，需 fonttools 按字形映射表还原文字
- 提交：`POST /mooc-ans/work/addStudentWorkNew`（表单 + `answer{qid}`/`answertype{qid}`/`answerwqbid`/`pyFlag`，pyFlag 空=提交、1=仅保存）
- 题库对接：言溪 / 网课小工具 / AI(OpenAI 兼容) 等，链式回退 + 本地缓存

## 6. 请求头备忘

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/118.0.0.0 Safari/537.36
视频 Referer: https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=...
音频 Referer: https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v=...
课程接口 Referer: https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=...
```
