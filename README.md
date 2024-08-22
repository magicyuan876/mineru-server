# MinerU 简单实现一个API服务
## 按照MinerU的官方文档先把环境该装的装好，然后可以自己写个脚本执行项目中的 main.py 
### 提供两个API
  1. 第一个upload 支持上传文件以及传入的username 创建独立的文件目录用于识别处理
  2. 第二个download 根据第一个接口返回的task_id来获取解析后的MD文件，文件转为base64在json中返回

### 修改为使用命令行执行MinerU，避免显存长期驻留不释放的问题
