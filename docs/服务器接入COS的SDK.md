第一步：安装 COS Python SDK

```bash
pip3 install cos-python-sdk-v5
```

复制

第二步：把密钥放进环境变量，不写进代码

在服务器的服务配置里注入（例如在 systemd 的 `Environment=` 中，或放在一个权限 600 的 `.env` 文件里），变量名自行定义：

```bash
export COS_SECRET_ID="你保存的 SecretId"
export COS_SECRET_KEY="你保存的 SecretKey"
```

复制

SecretKey 已经无法事后查询，只能使用创建时保存的那一份，因此这些值务必只放在服务器这一处，不要进入代码仓库或日志。

第三步：初始化客户端并上传

SDK 会自动计算请求签名，你只需在初始化时配置好密钥，不必自己处理签名。

```python
# -*- coding=utf-8 -*-
import os
from qcloud_cos import CosConfig, CosS3Client

secret_id = os.environ['COS_SECRET_ID']
secret_key = os.environ['COS_SECRET_KEY']
region = 'ap-guangzhou'          # 必须是桶所在地域

config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
client = CosS3Client(config)

bucket = 'common-storage-1498376444'
with open('/tmp/example.pdf', 'rb') as f:
    client.put_object(
        Bucket=bucket,
        Key='papers/2026/example.pdf',
        Body=f.read()
    )
print('PutObject OK')
```

复制

密钥从环境变量读取、`Region` 填桶归属地域、`Bucket` 用「桶名」格式，这三点是官方示例里的标准写法。

第四步：验证

在服务器上跑完上面的脚本，然后回桶的「文件列表」看对象是否出现；概览页的请求数约有 2 小时延迟。也可以在代码里随即调用 `head_object` 确认文件"存在，且大小一致"。

几个容易遇到问题的点

- 地域写错：`Region` 必须是 `ap-guangzhou`，写成别的地域会走公网链路，既慢又产生外网流量。
- 403 AccessDenied：刚关联的策略有约一分钟缓存，等一下再试；仍失败就回用户详情页确认两条策略是否都在。
- SignatureDoesNotMatch：多半是环境变量没注入进程（比如 systemd 里没写、`export` 只在当前 shell 生效）。
- 大文件：几 MB 的 PDF 用 `put_object` 足够；如果将来有上百 MB 的文件，改用 SDK 的分块上传接口。
- 别把密钥打日志：排查时不要 `print(config)` 之类的输出。