# Python 基础面试复习：结合本项目讲清楚

> 适用场景：Python 后端、FastAPI、AI Agent 项目面试。  
> 复习方法：先按“简答版”口述，再用“结合项目”补充真实落地点，最后准备追问。

## 1. 项目里最适合引出的 Python 基础点

这个项目不是单纯调用大模型，而是一个完整 Python 后端。面试官问 Python 基础时，可以优先往这些代码点上靠：

| Python 基础点 | 项目落地点 | 可以强调什么 |
| --- | --- | --- |
| 类型注解 | `schemas.py`、`models.py`、`agent.py` | 可读性、编辑器提示、Pydantic 校验、SQLAlchemy 2 typed ORM |
| 可变/不可变对象 | `message_data: dict | None`、`list[NoteRead]` | 避免共享可变默认值，返回快照隔离历史数据 |
| 生成器 | `database.get_db()`、`AgentService.stream_chat()` | 请求级资源释放、SSE 流式输出 |
| 装饰器 | `@app.get`、`@app.post`、`@lru_cache` | FastAPI 路由注册、配置缓存 |
| 上下文管理器 | `with client.messages.stream(...)`、`with engine.connect()` | 自动释放网络连接和数据库连接 |
| 异常处理 | `HTTPException`、全局异常处理、`try/except/finally` | 错误响应稳定、事务回滚、资源关闭 |
| 面向对象 | `AuthService`、`NoteService`、`AgentService` | 高内聚：每个 Service 管自己的业务边界 |
| 函数是一等对象 | `note_retriever: Callable[...]` | Agent 层通过函数注入解耦数据库 |
| dataclass | `ParsedFile`、`ValidatedUpload` | 简洁表达内部数据结构 |
| 泛型 | `ApiResponse[T]` | 统一响应信封，同时保留 data 类型 |
| async/sync | `async def upload_file` 与普通路由混用 | I/O 读取文件用 async，数据库 ORM 仍同步 |
| JSON 序列化 | `_sse_event()`、Pydantic serializer | 中文、换行、时间格式稳定 |

## 2. 自我介绍项目时的 Python 角度话术

简答版：

> 这个项目是一个 FastAPI 后端，核心 Python 能力主要体现在类型化接口、分层服务、生成器流式输出和资源管理上。`schemas.py` 用 Pydantic 做请求响应校验，`models.py` 用 SQLAlchemy 2 的类型化 ORM 定义表结构，`services.py` 控制事务和权限，`agent.py` 通过函数注入和 LangGraph 解耦模型编排。聊天接口用生成器产出 SSE 事件，文件上传用 dataclass 统一解析结果，整体尽量做到高内聚、低耦合。

展开版：

> 我把 Route、Service、CRUD、Agent 和 Storage 做了分层。Route 只处理 HTTP 协议和依赖注入；Service 负责业务规则、事务和权限校验；CRUD 只做 SQLAlchemy 查询，不提交事务；Agent 只接收问题和检索函数，不直接依赖数据库。这样面试官问 Python 基础时，我可以结合代码解释生成器、装饰器、类型注解、异常处理、上下文管理器和面向对象设计，而不是只背概念。

## 3. 高频题与详细答案

### 1. Python 变量到底保存的是值还是引用？

简答版：

Python 变量保存的是对象引用。赋值不是拷贝对象，而是让变量名绑定到对象。可变对象可以在 `id` 不变的情况下修改内容，不可变对象修改时会创建新对象。

结合项目：

`AgentService.stream_chat()` 里有：

```python
answer_parts: list[str] = []
for text_delta in agent.stream_answer(data.question, used_notes):
    answer_parts.append(text_delta)
```

这里 `answer_parts` 是可变 list，`append` 是原地修改，适合逐段收集模型输出。最后再 `"".join(answer_parts)` 拼接成字符串，避免循环里反复做字符串拼接。

常见追问：

为什么不用 `answer += text_delta`？

因为 `str` 是不可变对象，每次 `+=` 都可能创建新字符串。片段多时，先放 list 再 join 更合适。

### 2. 可变对象和不可变对象有什么区别？为什么默认参数不能写 `[]`？

简答版：

可变对象如 `list`、`dict`、`set` 可以原地修改；不可变对象如 `int`、`str`、`tuple` 不能原地改。函数默认参数在定义函数时只计算一次，如果用可变对象，会被多次调用共享。

错误示例：

```python
def collect(value: str, result: list[str] = []) -> list[str]:
    result.append(value)
    return result
```

正确写法：

```python
def collect(value: str, result: list[str] | None = None) -> list[str]:
    if result is None:
        result = []
    result.append(value)
    return result
```

结合项目：

`AgentMessageRead` 里使用：

```python
used_notes: list[NoteRead] = Field(default_factory=list)
```

这是 Pydantic 推荐方式。它每次创建模型都会生成新的 list，避免多个响应对象共享同一个默认列表。

### 3. `==` 和 `is` 有什么区别？

简答版：

`==` 比较值是否相等，通常调用对象的 `__eq__`；`is` 比较两个变量是否引用同一个对象。判断 `None` 应该用 `is None`。

结合项目：

`_save_user_message()` 里判断：

```python
if data.session_id is None:
    session = crud.add_agent_session(self.db, owner_id, data.question)
```

这里用 `is None` 是正确的，因为 `None` 是单例，也避免被自定义相等逻辑影响。

### 4. Python 的类型注解有什么用？运行时会强制校验吗？

简答版：

类型注解主要提升可读性、编辑器提示和静态检查，本身不会自动强制运行时校验。但 FastAPI 和 Pydantic 会读取类型注解，在请求进入时做数据校验和序列化。

结合项目：

`schemas.py` 里：

```python
class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
```

这不只是注释。FastAPI 会用它校验请求体，如果标题为空或超过长度，会直接返回 422，不会进入 Service。

再比如 `models.py` 使用 SQLAlchemy 2 写法：

```python
title: Mapped[str] = mapped_column(String(200), index=True)
```

它同时表达 Python 类型和数据库列配置，读代码时能直接知道字段类型。

### 5. Pydantic Schema 和 SQLAlchemy Model 为什么要分开？

简答版：

Schema 是 API 边界合同，负责输入校验、输出裁剪和序列化；Model 是数据库持久化结构。两者分开可以避免数据库内部字段直接暴露给前端。

结合项目：

`models.User` 有 `hashed_password`，但 `schemas.UserRead` 没有这个字段：

```python
class UserRead(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime
```

这样即使路由返回 ORM 对象，响应模型也只会输出允许暴露的字段，不会把密码哈希返回给浏览器。

常见追问：

`model_config = ConfigDict(from_attributes=True)` 是做什么的？

它允许 Pydantic 从 ORM 对象属性中读取字段。比如把 `models.Note` 转成 `schemas.NoteRead` 时，不需要手动一个字段一个字段复制。

### 6. 生成器是什么？项目里哪里用了生成器？

简答版：

生成器是惰性迭代器，使用 `yield` 每次产出一个值并暂停，下一次继续从暂停位置执行。它适合大文件、流式响应和资源生命周期控制。

结合项目一：数据库 Session

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

FastAPI 会执行到 `yield` 把 `db` 注入路由，请求结束后继续执行 `finally`，保证连接关闭。

结合项目二：SSE 流式输出

```python
yield _sse_event("delta", {"content": text_delta})
```

`stream_chat()` 不需要等模型完整回答生成后再返回，而是每拿到一段文本就产出一个 SSE 事件，前端就能逐字或逐段展示。

### 7. `yield` 和 `return` 的区别是什么？

简答版：

普通函数执行到 `return` 就结束并返回一个结果；包含 `yield` 的函数调用后返回生成器对象，真正执行发生在迭代时，每次 `yield` 产出一个值并暂停。

结合项目：

`agent.stream_answer()` 使用：

```python
yield from _stream_model(SYSTEM_PROMPT, user_content)
```

它把底层模型流式输出直接委托给调用方。Service 可以边收到模型片段，边包装成 SSE 发送给前端。

追问：

为什么流式接口里要 `except GeneratorExit`？

当客户端断开连接时，生成器可能收到 `GeneratorExit`。项目里捕获后执行 `db.rollback()` 再抛出，避免半截事务停留。

### 8. 装饰器的原理是什么？项目里有哪些装饰器？

简答版：

装饰器本质是函数包装。`@decorator` 等价于 `func = decorator(func)`。它可以在不修改原函数主体的情况下增加注册、缓存、鉴权、日志等能力。

结合项目：

FastAPI 路由：

```python
@app.post("/notes", response_model=schemas.ApiResponse[schemas.NoteRead])
def create_note(...):
    ...
```

`@app.post` 会把函数注册成 HTTP 路由，并记录响应模型。

配置缓存：

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`@lru_cache` 会缓存 `Settings()` 结果，避免每次请求都重新读取 `.env`。

### 9. 什么是上下文管理器？为什么要用 `with`？

简答版：

上下文管理器通过 `__enter__` 和 `__exit__` 管理资源。`with` 可以保证无论正常结束还是异常退出，都执行释放逻辑。

结合项目：

`database.py`：

```python
with engine.connect() as connection:
    connection.execute(text("SELECT 1"))
```

连接用完会自动归还连接池。

`agent.py`：

```python
with client.messages.stream(...) as stream:
    yield from stream.text_stream
```

模型流结束或异常时，会自动关闭底层网络流。

### 10. Python 异常处理在项目中怎么设计？

简答版：

业务可预期错误用 `HTTPException` 返回明确状态码；未知错误在全局异常处理里记录日志，并给前端脱敏后的 500。涉及数据库写操作时，异常要 rollback。

结合项目：

`BaseService._commit()`：

```python
def _commit(self) -> None:
    try:
        self.db.commit()
    except Exception:
        self.db.rollback()
        raise
```

这样写操作失败不会让 Session 留在错误状态。

`responses.py` 集中注册异常处理，把错误转换成统一格式：

```json
{"data": null, "code": 422, "message": "参数格式错误"}
```

面试可以强调：SSE 不同于普通 JSON 接口，连接建立后不能再改 HTTP 状态码，所以项目通过 `error` 事件通知前端。

### 11. `try/except/finally` 的执行顺序是什么？

简答版：

`try` 中执行正常逻辑，出错进入匹配的 `except`，无论是否出错通常都会执行 `finally`。`finally` 适合释放资源。

结合项目：

`AgentService.stream_chat()`：

```python
try:
    ...
except Exception:
    db.rollback()
    yield _sse_event("error", ...)
finally:
    db.close()
```

模型调用失败时，回滚事务并返回 SSE error；无论是否失败，最后都关闭数据库 Session。

### 12. 面向对象在这个项目里怎么体现？

简答版：

项目用类把相关业务行为聚合起来。`AuthService` 管认证，`NoteService` 管笔记，`AgentService` 管会话、消息、流式问答和表单。这样职责更清楚，调用方不用关心内部事务细节。

结合项目：

`BaseService` 封装公共提交回滚逻辑，其他 Service 继承它：

```python
class NoteService(BaseService):
    def create(...):
        ...
        self._commit()
```

这是高内聚的体现：和笔记相关的权限、事务、CRUD 编排都放在一个类里；同时低耦合：CRUD 不知道 HTTP，Agent 不知道数据库。

### 13. 函数是一等对象是什么意思？

简答版：

函数可以像普通变量一样赋值、传参、返回。装饰器、回调、依赖注入都依赖这个特性。

结合项目：

`agent.run_agent()` 接收一个检索函数：

```python
def run_agent(
    owner_id: int,
    question: str,
    note_retriever: Callable[[int, str], list[schemas.NoteRead]],
) -> tuple[str, list[schemas.NoteRead]]:
```

Agent 层不直接查询数据库，而是调用传入的 `note_retriever`。这让 Agent 模块更容易测试，也能替换成向量检索、缓存检索或 mock 检索。

### 14. `dataclass` 适合什么场景？项目里为什么用它？

简答版：

`dataclass` 适合表达内部数据结构，能自动生成初始化方法、比较方法等。它比普通 dict 更明确，比完整业务类更轻量。

结合项目：

`file_parser.py`：

```python
@dataclass(frozen=True)
class ParsedFile:
    name: str
    media_type: str
    size: int
    text: str
```

文件解析后的结果字段固定，用 frozen dataclass 可以减少后续模块意外修改解析结果的风险。

追问：

为什么不用 Pydantic？

这里是服务端内部结构，不直接作为 HTTP 入参。`dataclass` 更轻量；HTTP 边界才更适合用 Pydantic 做强校验和序列化。

### 15. `dict`、`list`、`set`、`tuple` 怎么选？

简答版：

`list` 用于有序可重复序列；`tuple` 用于固定不可变组合；`dict` 用于 key-value 映射；`set` 用于去重和快速成员判断。

结合项目：

`message_data` 用 `dict`，因为它要保存结构化元数据，例如引用快照、附件或表单状态。

`used_notes` 用 `list`，因为引用笔记需要保持顺序，且可能展示多条。

`SUPPORTED_EXTENSIONS` 用 `set`：

```python
SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}
```

因为校验文件后缀只关心“是否支持”，set 的成员判断平均复杂度是 `O(1)`。

### 16. 浅拷贝和深拷贝有什么区别？项目里有没有类似思想？

简答版：

浅拷贝只复制外层容器，内部对象仍共享；深拷贝会递归复制内部对象。业务里不一定真的调用 `copy.deepcopy`，但要知道什么时候需要“快照”隔离。

结合项目：

项目保存回答引用时没有只保存 Note id，而是保存 Note 快照：

```python
return {"used_notes": [note.model_dump(mode="json") for note in used_notes]}
```

这样历史回答展示的是当时引用的笔记内容。即使以后用户修改或删除原笔记，历史消息里的引用仍然稳定。这就是“快照隔离”的业务思想。

### 17. `async def` 和普通 `def` 有什么区别？

简答版：

`async def` 定义协程函数，适合等待异步 I/O，比如读取上传文件、网络请求。普通 `def` 是同步函数，适合 CPU 逻辑或同步库调用。FastAPI 可以同时支持两种路由。

结合项目：

上传接口：

```python
@app.post("/uploads")
async def upload_file(file: UploadFile = File(...), ...):
    content = await file.read()
```

这里读取上传文件是异步 I/O，所以用 `await`。但 SQLAlchemy Session 当前是同步 ORM，所以大部分数据库路由使用普通 `def`，保持模型简单。

追问：

是不是所有接口都应该写成 async？

不是。若内部主要调用同步数据库驱动或同步 SDK，盲目 `async` 不一定提升性能，还可能阻塞事件循环。要看依赖库是否支持异步。

### 18. 什么是依赖注入？FastAPI 的 Depends 有什么价值？

简答版：

依赖注入就是函数声明自己需要什么资源，由框架负责创建、传入和释放。它能减少重复代码，让鉴权、数据库 Session 等逻辑复用。

结合项目：

```python
def create_note(
    data: schemas.NoteCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
```

路由不需要手动解析 Token 或创建数据库连接，只声明需要 `db` 和 `current_user`。`get_current_user` 统一完成 JWT 解析和用户查询，所有受保护接口都能复用。

### 19. 为什么 CRUD 层不 commit？

简答版：

因为一次业务操作可能包含多个数据库动作，需要作为一个事务一起成功或一起失败。如果 CRUD 自己 commit，Service 就无法保证原子性。

结合项目：

提交聊天表单时，项目要在同一事务里创建 Note，并把表单消息标记为 completed：

```python
note = crud.add_note(...)
self.db.flush()
message.message_data = {...}
self._commit()
```

如果创建 Note 成功但更新表单失败，应该整体回滚。事务边界放在 Service 层更合理。

### 20. `flush` 和 `commit` 有什么区别？

简答版：

`flush` 是把当前 Session 的 SQL 发给数据库，让数据库生成主键等结果，但事务还没提交；`commit` 是提交事务，让修改真正生效。

结合项目：

`crud.add_agent_session()` 里：

```python
db.add(session)
db.flush()
return session
```

需要先拿到 `session.id`，才能继续插入消息。但此时还不提交，保证“创建会话 + 保存用户消息”仍在同一个事务里。

### 21. `rollback` 为什么重要？

简答版：

数据库操作失败后，Session 可能处于错误状态。如果不 rollback，后续继续使用这个 Session 可能报错，甚至造成事务边界混乱。

结合项目：

注册时可能发生并发写入同一个邮箱，虽然先查重了，但仍要靠数据库唯一索引兜底：

```python
except IntegrityError as error:
    self.db.rollback()
    raise HTTPException(status_code=409, detail="邮箱已注册，请直接登录") from error
```

这里 rollback 后再返回 409，既保证事务干净，也给用户稳定提示。

### 22. Python 中如何处理时间？为什么项目用 UTC？

简答版：

后端存储和接口输出尽量统一用 UTC，前端再按用户时区展示。这样跨时区部署、日志排查和 Token 过期判断更稳定。

结合项目：

JWT：

```python
expires_at = datetime.now(timezone.utc) + timedelta(minutes=...)
```

消息时间序列化：

```python
utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
return utc_value.isoformat().replace("+00:00", "Z")
```

SQLite 的时间可能是不带时区的 naive datetime，所以响应时显式补成 UTC。

### 23. JSON 序列化有什么坑？项目怎么处理 SSE？

简答版：

JSON 需要处理中文、换行、时间、复杂对象等。SSE 的 data 行必须是稳定字符串，所以项目先把 dict 序列化成 JSON。

结合项目：

```python
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
return f"event: {event}\ndata: {payload}\n\n"
```

`ensure_ascii=False` 让中文保持可读；`json.dumps` 会正确处理内容中的换行和引号，避免 SSE 格式被用户输入破坏。

### 24. `@property` 有什么用？项目里哪里用了？

简答版：

`@property` 可以把方法包装成只读属性，让调用方像访问字段一样访问计算结果。

结合项目：

`AgentMessage` 里：

```python
@property
def used_notes(self) -> list[dict]:
    ...
```

消息表只存 `message_data` JSON，但接口响应需要 `used_notes` 字段。用 property 可以从 JSON 中派生出响应字段，不需要额外数据库列。

### 25. `lru_cache` 为什么适合配置读取？

简答版：

配置通常进程启动后不频繁变化，读取 `.env` 和构造 Settings 没必要每次请求都做。`lru_cache` 可以缓存函数返回值。

结合项目：

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

好处是模块都通过 `get_settings()` 获取配置，既集中，又避免重复解析环境变量。测试时如果要切换配置，可以清理缓存后重新读取。

### 26. Python 模块分层如何体现高内聚低耦合？

简答版：

高内聚是相关逻辑放在一起，低耦合是模块之间只通过清晰接口交互，减少互相知道内部实现。

结合项目：

`main.py` 不直接写 SQL，只调用 Service；`crud.py` 不 commit，只负责查询和对象增删；`agent.py` 不依赖数据库，只接收 `note_retriever` 函数；`file_parser.py` 把多格式文件统一成 `ParsedFile`。

可以这样答：

> 我把“协议适配、业务事务、数据访问、模型调用、文件解析”拆开。这样后续把笔记检索从 SQL like 换成向量库时，优先改 Service 注入的检索函数和 Agent 上下文组织，不需要重写 HTTP 路由。

### 27. 项目中有哪些安全相关的 Python 基础实践？

简答版：

密码只存哈希，JWT 只放用户 id 和过期时间，异常响应脱敏，OSS 密钥只在后端读取，上传文件限制格式、大小和图片像素。

结合项目：

`security.py`：

```python
pwd_context.hash(password)
pwd_context.verify(plain_password, hashed_password)
```

bcrypt 自带随机 salt，不需要自己拼 salt。

`config.py` 生产环境校验：

```python
if self.secret_key in unsafe_secret_keys or len(self.secret_key) < 32:
    raise ValueError(...)
```

可以说明：项目在启动时尽早拒绝危险配置，比上线后靠人工发现更可靠。

### 28. 项目中的 RAG 检索为什么要保存引用快照？

简答版：

因为历史回答应该对应当时模型看到的上下文。只保存 note id 会导致以后笔记变更后，历史引用内容也跟着变，影响可追溯性。

结合项目：

`_note_message_data()` 保存：

```python
{"used_notes": [note.model_dump(mode="json") for note in used_notes]}
```

这体现了 Python 序列化和业务设计的结合：把 Pydantic 对象转成 JSON 友好的 dict，再存入 `message_data`。

### 29. 如果面试官问这个项目有什么不足，怎么答？

务实回答：

> 当前项目是学习和面试展示项目，已经有认证、权限隔离、事务、SSE、文件解析和 OSS，但也有可继续优化的地方。笔记检索现在主要是数据库 like 关键字匹配，数据量上来后应该换成向量检索加 rerank；同步 SQLAlchemy 在高并发流式场景下要关注连接池压力；SSE 当前保存完整回答在流结束后完成，如果客户端断开，可以进一步设计断点保存；文件解析还可以加入异步任务队列和病毒扫描。

注意：

不要把这些优化说成已实现。面试里区分“已完成”和“可改进”很重要。

### 30. 请你现场写一个简单的 SSE 生成器

参考答案：

```python
import json
from collections.abc import Generator


def sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def stream_mock_answer(answer: str) -> Generator[str, None, None]:
    yield sse_event("start", {"ok": True})
    for index in range(0, len(answer), 5):
        yield sse_event("delta", {"content": answer[index:index + 5]})
    yield sse_event("done", {})
```

讲解点：

- 生成器不一次性返回完整内容。
- 每次 `yield` 一个符合 SSE 格式的字符串。
- `json.dumps` 避免中文、换行和引号破坏协议。

### 31. 请你现场写一个安全的部分更新函数

参考答案：

```python
def apply_note_update(note, data) -> None:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(note, key, value)
```

结合项目：

`NoteUpdate` 里字段都是可选的。`exclude_unset=True` 表示只更新用户真正传入的字段，不会把没传的字段改成 `None`。

追问：

为什么不能直接 `data.model_dump()`？

因为没传的可选字段会带默认值 `None`，可能误清空原数据。

### 32. 请解释 `with_for_update()` 的作用

简答版：

`with_for_update()` 会在事务中对查询到的行加锁，常用于防止并发重复处理同一条记录。

结合项目：

`submit_note_form()` 提交结构化表单时，会先锁定消息：

```python
select(models.AgentMessage)
    .join(models.AgentSession)
    .where(...)
    .with_for_update()
```

如果两个请求同时提交同一张表单，行锁能让它们串行处理。第一个提交后把状态改成 completed，第二个再进来时就会走幂等返回或冲突处理，避免重复创建笔记。

### 33. 为什么 `except Exception as exc` 后要 `raise ... from exc`？

简答版：

`raise new_error from exc` 可以保留异常链，日志和调试时能看到原始异常原因，同时对外返回更友好的错误。

结合项目：

`file_parser.py` 中解析失败时：

```python
raise HTTPException(
    status_code=422,
    detail="文件内容无法解析，请确认文件没有损坏或加密。",
) from exc
```

前端看到稳定提示，后端调试时仍能追踪到底层异常。

### 34. 项目里为什么用 `Path(filename).name`？

简答版：

这是为了去掉用户上传文件名里的路径部分，避免路径穿越或把客户端本地路径带入服务端逻辑。

结合项目：

```python
safe_name = Path(filename or "upload").name
```

如果用户传入 `../../secret.txt`，最终只取 `secret.txt`。虽然项目没有把上传文件直接写本地路径，这仍然是良好的输入清洗习惯。

### 35. 如果让你优化 Python 性能，你会从哪里看？

务实回答：

> 我会先看真实瓶颈，而不是盲目改代码。这个项目里可能的瓶颈有：数据库查询、模型流式调用、文件解析 OCR、图片压缩和 OSS 上传。优化顺序上，我会先加日志和耗时指标，再看慢 SQL、连接池、文件大小限制和模型超时。Python 层面可以避免循环字符串拼接、控制大文件内存占用、把 OCR 或长任务放到后台队列。

结合项目可说：

- 已经用 list 收集模型片段后 `join`。
- 已经限制 `MAX_FILE_SIZE`、`MAX_EXTRACTED_CHARS`、`MAX_IMAGE_PIXELS`。
- 流式模型调用前主动结束只读事务，避免长期占用数据库连接。

## 4. 面试官常见追问速答

### FastAPI 为什么快？

FastAPI 基于 Starlette 和 ASGI，支持异步 I/O；同时利用类型注解和 Pydantic 自动完成校验和 OpenAPI 文档。真正性能还取决于数据库、外部模型、连接池和部署方式。

### Python GIL 是什么？会影响这个项目吗？

GIL 是 CPython 的全局解释器锁，同一进程内多个线程不能同时执行 Python 字节码。这个项目主要是 Web I/O、数据库 I/O、模型网络 I/O，GIL 不是第一瓶颈。OCR、图片处理这类 CPU 密集任务增多时，可以考虑进程池、任务队列或独立服务。

### 深拷贝是不是越安全越好？

不是。深拷贝可能很慢，也可能复制不了连接、锁、文件句柄等资源。业务上只需要明确哪些数据要隔离。这个项目保存引用快照时，是把 Pydantic DTO 转成 JSON dict，而不是盲目 deepcopy 整个 ORM 对象。

### 为什么不用全局数据库 Session？

Session 代表一次工作单元，不适合作为全局共享对象。请求之间共享 Session 会造成事务污染、连接泄露和并发问题。项目用 `get_db()` 为每个请求创建独立 Session，请求结束关闭。

### 为什么 SSE 流式接口里不用普通请求级 `Depends(get_db)`？

流式响应的生命周期可能比普通请求长。项目在 `stream_chat()` 内部创建独立 Session，并把模型调用前后的数据库操作拆成短事务，避免模型生成期间长时间占用连接或持有事务。

### `rollback()` 会撤销所有东西吗？

只撤销当前未提交事务中的修改。已经 commit 的内容不会被 rollback。比如流式聊天中，用户消息先保存成功后再调用模型，后续模型失败不会自动删除已经提交的用户消息。

### `expire_on_commit=False` 是什么？

SQLAlchemy 默认 commit 后可能让对象属性过期，下次访问再从数据库加载。项目设置 `expire_on_commit=False`，减少提交后读取对象字段时的额外查询。需要数据库生成值时，仍通过 `refresh()` 获取最新状态。

## 5. 建议背熟的 8 个项目回答

1. 项目分层：Route 处理 HTTP，Service 处理业务和事务，CRUD 处理 SQL，Agent 处理模型编排。
2. Schema 和 Model 分离：避免把 `hashed_password` 等内部字段暴露给前端。
3. 生成器：`get_db()` 管资源释放，`stream_chat()` 管 SSE 流式输出。
4. 事务边界：CRUD 不 commit，Service 统一 commit/rollback。
5. 权限隔离：所有 Note 和 Session 都用 `owner_id` 校验，越权统一返回 404。
6. 配置管理：Pydantic Settings + `lru_cache`，生产环境拒绝弱密钥和 SQLite。
7. 文件解析：先校验大小和格式，再按类型抽取文本或 OCR，最后统一成 `ParsedFile`。
8. Agent 解耦：`agent.py` 通过 `Callable` 接收检索函数，不直接依赖数据库。

## 6. 面试前 20 分钟复习顺序

1. 先读 `README.md` 的项目能力和目录职责。
2. 再读 `app/main.py`，记住每类接口：认证、Notes、Agent、文件、OSS、表单。
3. 重点看 `app/services.py`，这是面试深挖最多的地方。
4. 看 `app/schemas.py` 和 `app/models.py`，准备讲 Schema/Model 分离。
5. 看 `app/agent.py`，准备讲生成器、函数注入和 LangGraph。
6. 最后背本文件第 5 节的 8 个回答。

