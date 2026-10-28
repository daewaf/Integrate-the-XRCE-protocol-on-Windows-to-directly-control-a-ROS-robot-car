# DDS-XRCE 1.0 最小实现笔记

来源：OMG DDS-XRCE 1.0 规范（本地提取文本 `omg_spec_extract.txt`）。
凡标注「待抓包验证」的，均需用真实主控板抓包确认。

## 1. 消息头（8.3.2）

| 字段 | 宽度 | 字节序 | 含义 |
|---|---|---|---|
| sessionId | 1 B | — | 0x00–0x7F 时头部带 clientKey；0x80–0xFF 时由源地址界定会话 |
| streamId | 1 B | — | 0x00=无流；0x01=内置 best-effort；0x80=内置 reliable |
| sequenceNr | 2 B | 小端 | 每个流独立计数 |
| clientKey | 4 B | 小端 | 仅当 sessionId ≤ 0x7F 时出现 |

会话特殊值：0x00 = SESSION_ID_NONE_WITH_CLIENT_KEY，0x80 = SESSION_ID_NONE_WITHOUT_CLIENT_KEY。

## 2. 子消息头（8.3.4）

| 字段 | 宽度 | 字节序 | 含义 |
|---|---|---|---|
| submessageId | 1 B | — | 见下表 |
| flags | 1 B | — | bit0 = Endianness（1=小端）；bit1 Reuse；bit2 Replace |
| submessageLength | 2 B | **恒小端** | 不含子消息头 |

子消息起点按 4 字节对齐，必要时补零。

### SubmessageId（Table 10）

| 名称 | 值 | 方向 |
|---|---|---|
| CREATE_CLIENT | 0x00 | Client → Agent |
| CREATE | 0x01 | Client → Agent |
| GET_INFO | 0x02 | Client → Agent |
| DELETE | 0x03 | Client → Agent |
| STATUS_AGENT | 0x04 | Agent → Client |
| STATUS | 0x05 | Agent → Client |
| INFO | 0x06 | Agent → Client |
| WRITE_DATA | 0x07 | Client → Agent |
| READ_DATA | 0x08 | Client → Agent |
| DATA | 0x09 | Agent → Client |
| ACKNACK | 0x0A | 双向 |
| HEARTBEAT | 0x0B | 双向 |
| RESET | 0x0C | 双向 |
| FRAGMENT | 0x0D | 双向 |
| TIMESTAMP | 0x0E | 双向 |
| TIMESTAMP_REPLY | 0x0F | 双向 |

## 3. CREATE_CLIENT（8.3.5.1）

规范里存在两个版本的 `CLIENT_Representation`：

**版本 A（8.3.5.1，无时间戳）**

| 字段 | 宽度 | 说明 |
|---|---|---|
| xrce_cookie | 4 B | ASCII `"XRCE"` |
| xrce_version | 2 B | `{major, minor}`，常见 `{0x01, 0x00}` |
| xrce_vendor_id | 2 B | `{vendor_id[0], vendor_id[1]}` |
| client_key | 4 B | 客户端密钥 |
| session_id | 1 B | 请求的会话号 |
| properties? | 1 B | 0=不存在，1=存在（后续为 PropertySeq） |

合计 14 B。B.1 示例给出的 `submessageLength = 26` 与逐字段合计不一致（待抓包验证）。

**版本 B（7.8.2.1，带 client_timestamp）**：在 vendor 与 client_key 之间多 8 B `Time_t {int32 sec, uint32 nsec}`，合计 22 B；再加 4 B（可能是 request/object）正好 26 B，与 B.1 的长度吻合（待抓包验证）。

## 4. STATUS_AGENT（8.3.5.5）

`AGENT_Representation`：

| 字段 | 宽度 | 说明 |
|---|---|---|
| xrce_cookie | 4 B | `"XRCE"` |
| xrce_version | 2 B | Agent 协议版本 |
| xrce_vendor_id | 2 B | Agent 厂商 |
| agent_timestamp | 8 B | 7.8.2.1 版本包含；8.3.5.5 的 IDL 省略（待抓包验证） |
| properties? | 1 B | 0=不存在 |

## 5. ObjectId / ObjectKind（7.7.5 / 7.7.6）

ObjectId 2 字节：`byte0 = prefix[0]`，`byte1 = (prefix[1] & 0xF0) | kind`。

| kind | 值 |
|---|---|
| PARTICIPANT | 0x01 |
| TOPIC | 0x02 |
| PUBLISHER | 0x03 |
| SUBSCRIBER | 0x04 |
| DATAWRITER | 0x05 |
| DATAREADER | 0x06 |
| TYPE | 0x0A |
| QOSPROFILE | 0x0B |

特殊值：`{0x00,0x00}` = INVALID；`{0xFF,0xFE}` = CLIENT。

## 6. CREATE（8.3.5.2）

payload = `BaseObjectRequest` + `ObjectVariant`：

| 字段 | 宽度 | 说明 |
|---|---|---|
| request_id | 2 B | 请求关联用 |
| object_id | 2 B | 目标对象前缀 |
| ObjectVariant discriminator | 1 B | 等于 ObjectKind |
| Representation discriminator | 1 B | 0x03 = IN_BINARY |
| padding | 2 B | 32 位对齐 |
| representation body | 变长 | 例如 DataWriter 的 `topic_name` + 可选 qos |
| 尾部 | 2 B | 例如 publisher_id / subscriber_id |

B.2.3 示例（DataWriter，topic `"Square"`）：

```
0x81 0x00 0x80 0x07            # session 1, stream reliable, seq 7
0x01 0x07 0x1A 0x00            # CREATE, flags, len=26
0xAA 0x01 0xDD 0xD5            # request_id, object_id
0x05 0x03 0x00 0x00            # kind=DATAWRITER, IN_BINARY, padding
0x0C 0x00 0x00 0x80            # DHEADER (appendable, len=12)
0x07 0x00 0x00 0x00            # string length incl. NUL
53 71 75 61 72 65 00 00        # "Square\0" + qos absent
0xBB 0xB3                      # publisher_id
```

## 7. WRITE_DATA（8.3.5.8）与 DATA（8.3.5.10）

两者 payload 都是：`request_id(2) + object_id(2) + XCDR serialized sample`。

- WRITE_DATA：Client → Agent（客户端 DataWriter 上报）
- DATA：Agent → Client（下发到客户端 DataReader）

`geometry_msgs/msg/Twist` 的 CDR：6 个 `float64`，顺序
`linear.x, linear.y, linear.z, angular.x, angular.y, angular.z`，共 48 B，小端。

## 8. STATUS（8.3.5.6）

`BaseObjectReply` = `related_request(request_id 2 + object_id 2)` + `status(1)` + `implementation_status(1)`，共 6 B。成功时 status=0x00。

## 9. 可靠流

streamId 128 为可靠流，需要 HEARTBEAT/ACKNACK 维护窗口。最小实现优先让客户端走内置 best-effort(0x01)；若客户端坚持可靠流，必须在收到 HEARTBEAT 后回 ACKNACK，字段布局待抓包确认（规范 8.3.5.11/12）。

## 10. 当前实现状态

- `xrce/frame.py`：消息头、子消息头、编解码 —— 已通过单测
- `xrce/cdr.py`：CDR 读写、Twist 序列化 —— 已通过单测
- `xrce/agent.py`：UDP 监听、CREATE_CLIENT 应答、CREATE→STATUS OK、WRITE_DATA 记录、DATA 下发
- 待验证：真实主控板的 CREATE_CLIENT 实际布局、客户端是否使用可靠流、DATA 下发是否需要等待 READ_DATA 轮询
