# collect_openverse.py 修复说明

## 背景

本仓库用于构建工笔画 LoRA 数据集。`scripts/collect_openverse.py` 是数据生产链路里的第一步：从 Openverse 搜索开放授权图片，下载原始图片，并把图片元数据写入数据集 manifest，供后续豆包候选图生成、人工审核和训练使用。

当前运行环境无法成功访问 Openverse API。脚本在 API 请求阶段全部失败，因此没有进入图片下载和尺寸过滤阶段。

## 相关文件

- `scripts/collect_openverse.py`：需要修复或增强诊断能力的主脚本。
- `configs/pipeline_gongbi_v1.json`：当前运行配置。
- `configs/pipeline_gongbi_v1.json.example`：配置模板，包含 Openverse 参数。
- `scripts/pipeline_common.py`：数据集路径、JSONL、图片尺寸、hash、slug 等通用工具。
- `scripts/import_raw_assets.py`：Openverse 不可用时，可用来导入本地图片的替代路径。
- `requirements.txt`：运行依赖，主要是 `requests`、`pillow`、`urllib3`。
- `data/gongbi_v1/manifests/openverse_failures.jsonl`：当前失败记录文件。

## 脚本功能

`collect_openverse.py` 的主要流程如下：

1. 读取命令行参数：

   ```bash
   python scripts/collect_openverse.py \
     --config configs/pipeline_gongbi_v1.json \
     --dataset-dir data/gongbi_v1
   ```

2. 读取配置文件，得到：

   - 数据集目录。
   - 图片尺寸下限。
   - Openverse API endpoint。
   - license、page_size、sleep_seconds、retry、backoff、source 等过滤条件。
   - categories 中每个分类的 name、target_count、queries。

3. 初始化 Openverse client：

   - 如果存在 `OPENVERSE_ACCESS_TOKEN`，使用 Bearer token。
   - 否则如果存在 `OPENVERSE_CLIENT_ID` 和 `OPENVERSE_CLIENT_SECRET`，先请求 auth endpoint 获取 token。
   - 如果都不存在，使用 anonymous mode。

4. 按分类和 query 搜索 Openverse：

   - 请求 `https://api.openverse.org/v1/images/`。
   - 参数包括 `q`、`license`、`page`、`page_size`、`mature=false`。
   - 可选参数包括 `size`、`source`、`excluded_source`。
   - API 请求对 429 和 5xx 有重试，使用指数退避。

5. 对每条搜索结果做下载候选：

   - 优先使用 `item["url"]`。
   - 如果源图下载失败，会尝试 `item["thumbnail"]`。

6. 过滤和去重：

   - 已见过的 `source_url` / `download_url` 跳过。
   - 已见过的 `openverse_id` 跳过。
   - 已见过的文件 sha256 跳过。
   - 声明尺寸和实际图片尺寸都需要满足配置下限。

7. 写入结果：

   - 图片保存到 `data/gongbi_v1/raw/images/<category>/`。
   - 成功记录写入 `data/gongbi_v1/manifests/raw_assets.jsonl`。
   - API 或下载失败写入 `data/gongbi_v1/manifests/openverse_failures.jsonl`。

## 命令行参数

脚本当前支持：

```text
--config          配置文件，默认 configs/pipeline_gongbi_v1.json
--dataset-dir     数据集输出目录，会覆盖 config 中的 dataset_dir
--max-downloads   本次最多下载多少张，适合小规模试跑
--mock-response   使用本地 Openverse mock JSON，不请求真实 API
--timeout         API 和图片下载超时时间，默认 30 秒
```

建议修复后用小规模命令验收：

```bash
python scripts/collect_openverse.py \
  --config configs/pipeline_gongbi_v1.json \
  --dataset-dir data/gongbi_v1 \
  --max-downloads 5
```

## 当前故障现象

用户运行后完整结束，但没有抓到图片：

```text
done: downloaded=0, skipped=0, api_failures=12, download_failures=0, size_failures=0
```

失败日志里每个 query 都是同一种错误：

```text
failure_kind=ssl_error
SSLEOFError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol
```

手动 `curl` 也复现：

```bash
curl -Iv 'https://api.openverse.org/v1/images/?q=test&page_size=1'
```

输出关键部分：

```text
Uses proxy env variable https_proxy == 'http://172.16.0.13:5848'
CONNECT api.openverse.org:443 HTTP/1.1
HTTP/1.1 200 Connection established
TLSv1.3 (OUT), TLS handshake, Client hello (1)
TLS alert, decode error
error:0A000126:SSL routines::unexpected eof while reading
curl: (35) error:0A000126:SSL routines::unexpected eof while reading
```

代理接受了 CONNECT 隧道，但在后续 TLS 握手阶段连接被断开。脚本和 `curl` 失败在同一层，因此当前不是 Python 代码解析、图片过滤、license、query 或 OAuth 的问题。

## 当前环境线索

当时环境变量包含：

```text
http_proxy=http://172.16.0.13:5848
https_proxy=http://172.16.0.13:5848
all_proxy=socks5://172.16.0.13:5848
REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
```

`curl` 到 `https://www.cloudflare.com/` 可以成功，但到 `https://api.openverse.org/` 和 `https://openverse.org/` 失败。说明不是所有 HTTPS 都坏，而是当前代理/网络对 Openverse 相关域名不可用或 DNS/路由异常。

Openverse 官方文档仍指向 API 根地址：

```text
https://api.openverse.org/v1/
```

因此不要把 endpoint 改成随机域名作为主要修复。历史域名 `api.openverse.engineering` 会重定向回 `api.openverse.org`，不能作为稳定替代入口。

## 修复需求

### 必须完成

1. 先确认网络层可达：

   ```bash
   curl -Iv 'https://api.openverse.org/v1/images/?q=test&page_size=1'
   ```

   这条命令必须能返回 HTTP 200、HTTP 401/403 JSON 错误，或至少完成 TLS 握手并收到 HTTP 响应。只要仍然是 `unexpected eof while reading`，脚本不可能成功。

2. 在可达网络下运行小规模抓取：

   ```bash
   python scripts/collect_openverse.py \
     --config configs/pipeline_gongbi_v1.json \
     --dataset-dir data/gongbi_v1 \
     --max-downloads 5
   ```

3. 验证至少生成：

   ```text
   data/gongbi_v1/raw/images/<category>/*.jpg|*.png|*.webp
   data/gongbi_v1/manifests/raw_assets.jsonl
   ```

4. 终端出现类似：

   ```text
   collected <asset_id>: <width>x<height> via source
   done: downloaded=5, ...
   ```


## 验收清单

- `curl -Iv 'https://api.openverse.org/v1/images/?q=test&page_size=1'` 能完成 TLS 并返回 HTTP 响应。
- `python scripts/collect_openverse.py ... --max-downloads 5` 能下载至少 5 张图片。
- `raw_assets.jsonl` 中新增记录，字段包含 `asset_id`、`category`、`source=openverse`、`source_url`、`download_url`、`license`、`image_path`、`sha256`、`width`、`height`。
- `openverse_failures.jsonl` 不再只出现 API 层 `ssl_error`。
- 若实现 preflight，网络失败时脚本能在 1 次检查后清楚退出，而不是把 12 个 query 全部重试一遍。

