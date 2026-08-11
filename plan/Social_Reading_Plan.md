# 用户共读（Social Reading）整体方案

状态：**方案已确认，待排期开发**（第 8 节的问题均已由用户逐条确认，决策已回填进对应章节）
关联需求：用户于 2026-08-11 提出的共读功能需求
关联文档：[MyReader Sync API](../document/MyBooks_Sync_API.md)、[Sync 实现方案](../document/Sync_IMPLEMENT_PLAN.md)、[Reading Stats Design](../document/Reading_Stats_Design.md)、[Toolbox Design](../document/Toolbox_Design.md)

> 本文档只做方案设计，不包含代码实现。文中 ✅ 标记的是已确认的产品/技术决策；第 8 节保留完整的问答记录作为决策依据存档。

---

## 0. 背景与目标

"共读"希望让用户在浏览/阅读书籍时，能感知到"这本书还有别人在读、别人怎么评价、别人划了哪些重点"，从而提升发现和阅读意愿。核心能力拆成两条线：

1. **社交层（新增）**：评分、评论（含审核/管理）、"在读/收藏/推荐人数"统计、首页推荐位、划线笔记的跨用户可见性。
2. **存储层改造（既有功能重构）**：`MyReaderSyncService` 从"每用户每书一个 JSON 文件"改为落库（表名 `reading_records`），为"查看别人的划线笔记"提供跨用户查询能力，同时保留断点续迁移、不停机迁移能力。

两条线在 `notes` 数据上有交叉：只有 notes 落库并且每条记录标了 `uid`，"阅读时查看其他用户的划线与笔记"才有查询基础；建议**先做存储层迁移，再做社交层**，两者可并行开发，最后联调。

---

## 1. 术语与范围

| 术语 | 含义 |
|---|---|
| 评分（rating） | ✅ 沿用当前 `book.rating` 的刻度（`v-rating length="10"`，即 Calibre 惯用的 0–10 半星刻度），用户评分与书籍元数据评分**刻度一致但是两套独立数据**，UI 上需要有明显区分（详情页头部现有的是只读的 Calibre 均分/元数据评分，新增的是"我的评分"，出现在评价对话框和评论卡片里，避免与页面顶部已有的 `v-rating` 混淆——文案上用"我的评分"/"用户评分"加以区分） |
| 评论（review） | 用户对某本书的一段文字点评，与评分是同一条记录（`book_reviews` 表）的两个字段 |
| 推荐（recommend） | ✅ 本次不做独立的"定向分享"功能，"提交评价 = 完成一次推荐"。管理端仍保留两个独立开关（详见 §2.1）：`ENABLE_BOOK_REVIEW` 控制评分评论功能本身，`ENABLE_BOOK_RECOMMEND_TO_OTHERS` 控制"评价是否作为推荐信号对外暴露"（即是否计入推荐人数 / 参与首页推荐位取数）——两个开关语义不同，保留两个是为了给管理员"开放评论但不想上首页推荐"这种场景留口子 |
| 划线/笔记（notes） | MyReader 客户端通过 `/api/sync` 上报的 `notes` 类记录（高亮、批注、书签），字段定义见 `MyBooks_Sync_API.md` §1.5 |
| 在读人数 | `ReadingState.read_state == 1` 的用户数 |
| 收藏人数 | `ReadingState.favorite == 1` 的用户数 |
| 推荐人数 | 已对该书提交过评价（`book_reviews`，且 `ENABLE_BOOK_RECOMMEND_TO_OTHERS=True`、状态为"通过"）的用户数 |

不在本次范围内（Non-goals）：
- 用户间关注/好友关系、私信、定向分享
- 评论的点赞/回复
- notes 的"回复/讨论"功能，只做"查看"

---

## 2. 功能拆解

### 2.1 "浏览与阅读"管理员设置（`admin/settings.vue` → `settings.reader` 分组）

写法与现有 `ENABLE_AUTHOR_INFO` 等一致（`webserver/settings.py` 加默认值 + `settings.vue` 的 `fields` 数组加一项 + 三个 locale 文件加文案）：

| Key | 说明 | 默认值 |
|---|---|---|
| `ENABLE_BOOK_REVIEW` | 允许用户对书籍进行评论及评分 | `True` |
| `REVIEW_REQUIRES_APPROVAL` | ✅ 评论需要审核后才能展示（新增，随 `ENABLE_BOOK_REVIEW` 一起展示，仅当其为 `True` 时可见/生效） | `False` |
| `ENABLE_BOOK_RECOMMEND_TO_OTHERS` | 允许用户向别的用户推荐书籍（语义见 §1"推荐"词条：评价是否计入推荐人数/首页推荐位） | `True` |
| `ENABLE_SHARED_NOTES` | 阅读时可查看其他用户的划线与笔记 | `True` |

全局管理员开关，关闭后对应功能在前端隐藏、后端接口拒绝（`CONF.get(...)` 现查，不需要重启）。

### 2.2 个人设置（`user/usersettings.vue`，与"接收新书提醒邮件"同组）

✅ `Reader` 表新增两个独立列（与 `allow_statistic` 风格一致，不用 `extra` JSON）：

| Key | 说明 | 默认值 |
|---|---|---|
| `show_home_recommendations` | 首页展示其他用户推荐 | `True` |
| `review_banned` | ✅ 是否被管理员禁止发表评论（§2.6 管理功能用，用户自己不可见/不可改，仅展示态由后端下发） | `False` |

若 `ENABLE_BOOK_REVIEW`（管理员总开关）为 `False`，`review_banned` 不生效展示（没有评论入口）；若用户 `review_banned=True`，评价入口在前端隐藏/禁用，后端接口也要拒绝（双重保险）。`user/info` 接口需要在返回体里加 `review_banned` 字段，供前端判断是否展示评价入口。

### 2.3 首页推荐位（`app/src/pages/index.vue`）

参考现有"随机推荐"卡片（`index.vue:40-66`，`get_random_books`）实现方式：

- 触发条件：`ENABLE_BOOK_RECOMMEND_TO_OTHERS=True` 且当前登录用户 `show_home_recommendations == True`。
- 数据源：最近 7 天内、状态为"通过"的评价所涉及的书，按最新评价时间倒序取 10 本（去重按书）。
- 若无符合条件的书，整个区块不渲染（同随机推荐块 `v-if` 写法）。
- ✅ 卡片需要叠加"推荐人"角标（头像+昵称，取该书最新一条评价的作者），视觉上参考详情页作者头像的展示方式。
- 后端：`GET /api/book/social-recommendations` 返回 `{books: [{...book, recommender: {avatar, nickname}}]}`，按 `book_reviews` 过滤 `status=approved AND update_time >= now-7d`，取 `book_id` 分组后取最新一条，截断 10 条。
- 排除：匿名/游客不展示（沿用登录态判断），已下架/删除的书需过滤（配合 §6 级联清理，理论上下架书不会再有存活的 `book_reviews` 行）。

### 2.4 书籍详情页（`app/src/pages/book/_bookid.vue`）

#### a) 阅读信息组件（v-rating 下方）

- 展示：`在读 N 人`、`收藏 N 人`、`推荐 N 人`，`v-chip`/文本+图标横排。
- 三项均为 0 的字段不展示；三项都为 0 时整个组件不渲染。
- ✅ 数据来源：新增轻量接口 `GET /api/book/:id/social-stats`，返回 `{reading_count, favorite_count, recommend_count}`，前端异步加载，不阻塞主详情接口。
- 计算方式：见 §4.2 的计数器方案（避免每次现查聚合）。

#### b) 评价入口（toggleFavorite 图标之后新增 like 图标）

- ✅ 图标：`mdi-thumb-up-outline` / `mdi-thumb-up`（未评价/已评价两态，与心形收藏、书签待读区分）。
- 若当前用户 `review_banned=True` 或 `ENABLE_BOOK_REVIEW=False`，该图标隐藏。
- 交互：点击弹出对话框（新组件 `BookReviewDialog.vue`）：
  - 上方：`v-rating`（可编辑，`length="10"`，与详情页现有只读评分刻度一致）
  - 下方：`v-textarea`（小尺寸多行评论框，✅ **允许为空**，只提交评分也可以）
  - 底部：取消 / 推荐（提交）按钮
  - 已有评价记录时预填充（编辑态）
- 提交后：刷新 §2.4a 统计条 + §2.4c 评论列表（自己那条置顶更新）；若 `REVIEW_REQUIRES_APPROVAL=True`，提交后状态为"未审核"，前端需要提示"评论待审核"（评论卡片里对当前用户自己仍可见，但需要有"待审核"标记；对其他用户不可见，见 §2.6）。
- 后端接口：
  - `GET /api/book/:id/review` — 取当前用户对该书的评价（预填充/编辑态判断）
  - `POST /api/book/:id/review` — upsert（一人一书唯一）；写入时若 `REVIEW_REQUIRES_APPROVAL=True` 则 `status=pending`，否则 `status=approved`
  - `DELETE /api/book/:id/review` — ✅ **预留**（当前 UI 无删除入口，后端实现，供后续暴露）；语义为用户自行清空自己的评价（软删除，`deleted_at` 置位，不同于 §2.6 管理员的"隐藏"）

#### c) 评论卡片（"其它书籍"卡片之上新增）

- ✅ 位置：插在 `推荐图书列表`（`suggestionBooks`）与 `同名图书列表`（`sameNameBooks`）**两个区块之上**（即这两个"其它书籍类"区块的共同上方）。
- 标题：`评论`。
- 展示形态：flat style 列表，每行：左侧头像+昵称，右侧上方评分（只读 `v-rating`），下方评论文本；`REVIEW_REQUIRES_APPROVAL=True` 且状态为"未审核"的自己的评论，追加一个"待审核"小标签。
- 排序：当前用户（如果已评价，且未被自己删除）置顶，其后按更新时间倒序；置顶项右侧追加"编辑"图标（复用 `BookReviewDialog`）；管理员登录时，**每一行**（不限于自己）右侧追加"删除"图标（§2.6 的管理员隐藏能力）。
- ✅ 分页与筛选：顶部增加日期范围选择（一周内 / 一个月内 / 三个月内，另加"全部"），列表分页加载。
- 后端接口：`GET /api/book/:id/reviews?range=7d|30d|90d|all&page=&page_size=`，只返回 `status=approved`（未审核/隐藏的仅对本人或管理员可见，按调用方身份决定是否额外附加自己的 pending/hidden 记录）。
- 匿名/未登录用户：只读展示已通过的评论，不显示编辑/评价/删除入口。
- ✅ 空状态：无评论时显示"暂无评论"占位；若当前用户还没有对该书的评价，卡片右上角显示一个"+"按钮，点击效果与点击详情页 like 图标一致（打开 `BookReviewDialog`），方便用户直接在评论区添加。

#### d) 评论审核与管理（新增，来自 §8 问题 3 的确认）

- 管理员在详情页评论卡片可删除任意用户的评论 → 后端把该条 `book_reviews.status` 置为 `hidden`（不是物理删除），对普通用户不再可见，作者本人重新打开自己的评价对话框时仍能看到自己写的内容并可重新编辑（编辑保存后按 `REVIEW_REQUIRES_APPROVAL` 规则重新走一次状态判定，即从 `hidden` 变回 `pending`/`approved`，避免用户永久卡在被隐藏状态无法申诉）。
- `book_reviews.status` 三态：`pending`（未审核）/ `approved`（通过）/ `hidden`（管理员屏蔽）。`REVIEW_REQUIRES_APPROVAL=False` 时新评价直接是 `approved`，跳过 `pending`。
- 后端接口：`DELETE /api/admin/book-reviews/:id`（管理员专用，语义是"隐藏"，映射到 `status=hidden`），复用/新增管理员权限校验（参考现有 admin 接口的鉴权装饰器）。

### 2.5 `MyReaderSyncService` 落库改造

详见 §5（表设计）、§7（迁移方案）。核心变化点：

1. `books`/`configs`/`notes` **三类记录**（✅ 确认三类都迁移，而不是只迁 config/notes）从"每 (uid, book_hash) 一份 JSON 文件"改为数据库表存储，表名 ✅ `reading_records`（原方案草稿叫 `sync_records`，已按确认重命名）。
2. `notes` 的每条记录需要保证有 `uid` 字段（迁移历史数据时补全；push 时如果调用方没传也用当前登录用户的 uid 兜底补上）。
3. ✅ `GET /api/sync` 直接在现有接口上加 `own`（`0`/`1`）参数，`SyncHandler` 只做透传，具体"要不要组装其他用户的批注数据"的逻辑全部在 `MyReaderSyncService` 内部处理（沿用现有"handler 薄、service 厚"的分工）：
   - `own=1` 或不传：只返回当前用户自己的记录（与现状行为一致）
   - `own=0`：额外按 `ENABLE_SHARED_NOTES` 开关，把该书（按 §5.2 的整型 `book_id` 匹配，而非 `book_hash` 字符串匹配）下**其他用户**的 `notes` 记录也并入返回（`books`/`configs` 类不涉及"查看他人"，只有 `notes` 有共读展示需求，因此 `own=0` 只对 `notes` 类生效，`books`/`configs` 始终只返回自己的；`book_id` 为负数的本地书籍天然不参与跨用户匹配，见 §5.2）
   - `ENABLE_SHARED_NOTES=False` 时，即使传 `own=0` 也只返回自己的记录（功能开关优先级高于参数）

---

## 3. 权限位小结（新增，来自 §8 问题 3 确认后的补充设计）

| 角色 | 能力 |
|---|---|
| 匿名/游客 | 只读评论列表（仅 `approved`） |
| 普通用户（`review_banned=False`） | 提交/编辑/（预留）删除自己的评价 |
| 普通用户（`review_banned=True`） | 评价入口隐藏，历史已提交的评价保留展示，不可再编辑 |
| 管理员 | 额外可"隐藏"任意用户评论（§2.4d）；后台"用户评论"管理页（§2.6）；用户管理页可切换某用户的 `review_banned` |

### 2.6 后台管理：用户评论管理页（新增）

- 位置：管理后台新增页面（如 `admin/book-reviews.vue`），入口从现有 admin 导航加一项。
- 展示：表格分页，列为 **书名 / 用户名 / 评分 / 评论内容 / 状态**（未审核 / 通过 / 隐藏）。
- 操作列按状态变化：
  - `未审核` → 显示"通过"、"屏蔽"两个操作
  - `通过` → 显示"隐藏"
  - `隐藏` → 显示"恢复"（恢复到 `approved`，若原本是 `REVIEW_REQUIRES_APPROVAL` 流程下由 `pending` 直接被屏蔽的，恢复目标状态按【实现时须保留"屏蔽前状态"】处理，见下）
- 后端：`GET /api/admin/book-reviews?status=&page=&page_size=`、`POST /api/admin/book-reviews/:id/moderate` body `{action: "approve"|"hide"|"restore"}`。
  - 实现建议：`book_reviews` 增加 `prev_status` 列（进入 `hidden` 前的状态快照），`restore` 时恢复为 `prev_status`，避免"未审核评论被屏蔽后恢复应该回到未审核还是通过"产生歧义。
- 用户管理页（现有 `admin/users.vue` 之类）：每个用户行操作追加"禁止发表评论" / "恢复发表评论"，对应 `PATCH /api/admin/users/:id` 或专门的 `POST /api/admin/users/:id/review-ban` 接口更新 `Reader.review_banned`。

---

## 4. 缓存与性能

### 4.1 通用缓存工具

✅ 引入一个通用轻量缓存工具（新文件，如 `webserver/services/cache.py`，提供 `TTLCache`：进程内 `dict` + 过期时间戳，`get_or_set(key, ttl, loader)` 风格接口，不依赖 Redis，与项目"单实例部署"的现状一致）。用途：

- 首页推荐位查询结果（TTL 建议 5–10 分钟）
- `GET /api/book/:id/social-stats` 的计数读取（配合 §4.2 的计数器方案，缓存主要是缓冲批量落库前的"脏读"窗口）
- `own=0` 共读 notes 查询结果（TTL 建议与客户端轮询间隔对齐，如 5 秒，见 §4.3）

### 4.2 阅读信息条计数器方案

✅【实现调整，2026-08 落地时收敛】§8 问题 17 的确认原话允许两个方案二选一（"可以使用计数器方案……或者在更新阅读状态时判断，如果对应计数字段不存在，就在阅读状态中统计一次更新进去"）。实现阶段选择了后者的简化版本：**不新增 `Item.count_*` 列**，改为 `BookReviewService.get_stats()` 对 `ReadingState`/`book_reviews` 做实时 `COUNT` 查询，结果经 §4.1 的通用 `TTLCache`（key=`book_social_stats:<book_id>`，TTL 60s）缓存。

- 理由：`favorite`/`read_state` 的写入点分散在既有代码的多处（`BookFavorite`/`BookWantToRead`/`BookReading` 等 handler，以及可能的批量操作、书籍删除等路径），逐一改造为增量 `+1`/`-1` 风险较高（容易遗漏某个写入点导致计数漂移，且难以在一次改动中审计完备）；而 `recommend_count` 的来源（`book_reviews`）完全由本次新增代码独占，才具备"增量维护不会漏埋点"的前提。
- `recommend_count` 单独看确实可以做成 `Item.count_recommend` 增量列，但为了让阅读信息条三个数字的实现方式统一、心智负担更低，最终三项都走同一套"TTLCache 包一层 COUNT 查询"的路径。
- 任一评价的新增/编辑/软删除/管理员操作都会显式 `invalidate` 对应 `book_id` 的缓存（`BookReviewService.invalidate_stats()`），保证评价类数字最多有一次请求的延迟；`favorite`/`read_state` 变化目前**未**显式 invalidate（尚未接入既有 handler），依赖 60s TTL 自然过期，属于已知的、有界的短暂延迟，可接受。
- 如果未来实测 `COUNT` 查询在大库场景下开销明显，再按原方案升级为 `Item` 计数器列，不影响接口对外形状（`GET /api/book/:id/social-stats` 返回结构不变）。

### 4.3 sync 落库的写入频率与批量合并

✅ 确认为 SQLite，客户端轮询频率高（3–5 秒），采用**队列 + 批量合并**方案，参考 `webserver/services/async_service.py` 里 `ReadingWriteBuffer` 的现有模式（内存缓冲 + 定时 flush）：

- 新增 `SyncWriteBuffer`（命名对齐 `ReadingWriteBuffer`），`push` 请求先写入内存缓冲（按 `(reader_id, book_hash, kind, record_id)` 做最后写入覆盖，同一条记录短时间多次更新只保留最新一次），不立即落库。
- 定时任务按固定周期把缓冲区内容批量 upsert 进 `reading_records` 表（一次事务提交多条，减少 SQLite 锁争用）。
- ✅ 合并周期常量化，新增配置项 `SYNC_DB_FLUSH_INTERVAL_SEC`（默认建议 `5`，与 `READING_STATS_FLUSH_INTERVAL_SEC` 保持同量级，可调），在 `webserver/settings.py` 中定义。
- 查询侧（`GET /api/sync` 的 pull、共读 `own=0` 的跨用户查询）优先读 §4.1 的 `TTLCache`，缓存未命中才查库；由于写入是缓冲的，读缓存/读库都可能读到"上一次 flush 之前"的状态，这个延迟量级（≤ `SYNC_DB_FLUSH_INTERVAL_SEC`）在产品上可接受（重要程度类似 `Reading` 心跳缓冲）。
- WS 广播（`broadcast_changed`）在数据实际落库后触发（即 flush 时机），而不是请求到达时立刻触发，避免通知了但对方 pull 还读不到最新数据。

### 4.4 共读 notes 数量与内存

✅ 单本书通过 `own=0` 返回的"他人 notes"，按更新时间排序，**最多返回最近 20 个用户**的记录（不是最多 20 条记录，是最多 20 个不同的 `uid`，每个 uid 下的 notes 全部返回），新增配置项 `SYNC_SHARED_NOTES_MAX_USERS`（默认 `20`）。

---

## 5. 数据模型设计

### 5.1 新表：`book_reviews`（评分 + 评论 + 审核状态）

✅ 表名由草稿 `reader_book_reviews` 改为 `book_reviews`。

```python
class BookReview(Base, SQLAlchemyMixin):
    __tablename__ = "book_reviews"

    STATUS_PENDING = "pending"    # 未审核
    STATUS_APPROVED = "approved"  # 通过
    STATUS_HIDDEN = "hidden"      # 管理员屏蔽

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_id = Column(Integer, nullable=False)
    rating = Column(Integer, nullable=False)            # 沿用 book.rating 刻度（0-10）
    comment = Column(Text, default="")                   # 允许为空
    status = Column(String(16), nullable=False, default=STATUS_APPROVED)
    prev_status = Column(String(16), nullable=True)      # 进入 hidden 前的状态快照，供"恢复"使用
    create_time = Column(DateTime, nullable=False)
    update_time = Column(DateTime, nullable=False)
    deleted_at = Column(DateTime, nullable=True)          # 用户自行删除（软删除），与管理员 hidden 语义不同

    reader = relationship(Reader)

    __table_args__ = (
        UniqueConstraint("reader_id", "book_id", name="ux_book_review"),
        Index("ix_book_review_book", "book_id", "status", "update_time"),
    )
```

- 唯一约束 `(reader_id, book_id)` 保证"每个用户只能添加一条"；自行删除只是把 `rating`/`comment` 清空并置 `deleted_at`，不删行——这样"重新评价"直接复用同一行 upsert，不会撞唯一约束冲突。
- `status` 初值：`REVIEW_REQUIRES_APPROVAL=True` → `pending`；否则 → `approved`。
- 索引 `ix_book_review_book`：评论列表按书+状态+时间查询（§2.4c 的分页/日期筛选）。

### 5.2 sync 数据落库表设计：`reading_records`

✅ 表名由草稿 `sync_records` 改为 `reading_records`；三类记录（`books`/`configs`/`notes`）统一迁移。

```python
class ReadingRecord(Base, SQLAlchemyMixin):
    """`/api/sync` 记录的数据库存储，替代原 <uid>/<book_hash>/{kind}.json 文件。"""
    __tablename__ = "reading_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("readers.id"), nullable=False)
    book_hash = Column(String(64), nullable=False)      # 原始 book_hash，记录身份仍以它为准（同一 book_id 不同格式/本地文件会有不同 book_hash）
    book_id = Column(Integer, nullable=False)           # ✅ 新增：从 book_hash 提取的整型 book_id，供跨用户查询走整型索引
    kind = Column(String(16), nullable=False)          # books | configs | notes
    record_id = Column(String(64), nullable=False)     # books/configs: 固定用 book_hash 占位；notes: 记录自带的 id
    uid = Column(Integer, nullable=False)               # 冗余存一份 reader_id，同时也是需求要求写入 payload 内的 "uid"
    payload = Column(MutableDict.as_mutable(JSONType), nullable=False, default={})  # 记录原始 JSON 内容
    updated_at = Column(BigInteger, nullable=False)     # 毫秒时间戳，来自 payload.updated_at，冗余出来做索引/排序
    deleted_at = Column(BigInteger, nullable=True)      # 同上，冗余自 payload.deleted_at

    __table_args__ = (
        UniqueConstraint("reader_id", "book_hash", "kind", "record_id", name="ux_reading_record"),
        Index("ix_reading_record_lookup", "reader_id", "kind", "updated_at"),
        Index("ix_reading_record_book_kind", "book_id", "kind", "updated_at"),  # 供「查看他人笔记」跨用户查询，整型索引
    )
```

要点（与草稿一致，✅ 保留 JSON payload 方案，不拆结构化字段，但明确记录更新时间）：
- `payload` 直接存客户端原始记录（`BookRecord`/`BookNoteRecord`/`BookConfigRecord`），服务端不做字段白名单校验。
- `updated_at`/`deleted_at` 冗余列用于索引与 last-write-wins 判断，避免每次解析 JSON。
- ✅ **`book_id` 提取规则**：`book_hash` 用字符串做跨用户匹配索引效率低（`String` 索引 vs `Integer` 索引），新增 `book_id` 整型列，写入时按现有 `reading_stats_service.parse_book_id_from_hash()` 同款正则（`^cloud-(\d+)-[a-zA-Z0-9]+$`，MyBooks 云端书籍 `book_hash` 形如 `cloud-8502-epub`）提取 Calibre `book_id`；直接复用这个已有工具函数，不重复实现一套解析逻辑。
  - 提取成功（云端书籍）：`book_id` = 解析出的正整数。
  - 提取失败（本地导入书籍，没有对应的 Calibre `book_id`）：分配一个**负数占位值**（而不是正随机数）——取 `-abs(zlib.crc32(book_hash.encode()))`（或等价的稳定哈希取负），保证：① 一定是负数，天然与真实 `book_id`（恒为正）不冲突，跨用户查询按 `book_id > 0` 过滤即可自然排除所有本地书籍，不需要额外加一个"是否本地书籍"的布尔列；② 同一个 `book_hash` 每次计算结果一致（不用每次 push 都重新生成随机数导致同一本书在不同记录行里出现不同占位值，影响未来排查问题）。
- `ix_reading_record_book_kind` 支撑 §2.5/§4.4 的跨用户 notes 查询（按 `book_id + kind='notes' + book_id > 0` 取最近 `SYNC_SHARED_NOTES_MAX_USERS` 个不同 `uid`），整型等值查询，比原 `book_hash`（字符串）索引效率更高。

### 5.3 `Reader` 表新增列

```python
show_home_recommendations = Column(Boolean, default=True, nullable=False)  # 首页展示其他用户推荐
review_banned = Column(Boolean, default=False, nullable=False)              # 是否被禁止发表评论
```

### 5.4 `Item` 表新增列（§4.2 计数器方案）— 未采用

草稿阶段设计了 `count_reading`/`count_favorite`/`count_recommend` 三列，实现阶段按 §4.2 的说明改为 `TTLCache` 包一层实时 `COUNT` 查询，未新增这三列，`Item` 表结构不变。

---

## 6. 异常处理与边界情况

| 场景 | 处理建议 |
|---|---|
| 提交评分不填评论 | `comment` 存空字符串，评论卡片该行只显示评分 |
| 用户重复提交评价 | 唯一约束触发时走 upsert，不报错，走"编辑"语义 |
| 用户删除评价后又重新评价 | 复用同一行（清空 `deleted_at`），不会撞唯一约束 |
| 评价的书籍被删除/下架 | ✅ **需要级联清理**：删除书籍时同步删除该 `book_id` 对应的 `book_reviews` 行（物理删除或标记，与现有 `ReadingState` 对书籍删除的处理方式保持一致，需要在实现时确认 `ReadingState` 现有的级联删除代码位置并对齐同一处理入口）以及该书对应的所有用户 `reading_records`（现在有了 §5.2 的整型 `book_id` 列，直接 `DELETE ... WHERE book_id = ?` 即可，不需要先枚举 `book_hash` 再匹配，删除书籍的 handler/service 里一并触发） |
| `ENABLE_BOOK_REVIEW=False` 时已有历史评价数据 | 只关闭入口和展示，数据不删除 |
| `own=1` 但用户未登录 | 走现有 `@auth` 装饰器统一处理 |
| notes 记录里缺 `uid` | push 时用当前登录用户的 `reader_id` 兜底补齐；迁移时同理补齐（见 §7） |
| sync 迁移中断（进程重启/异常） | 见 §7，迁移可重入：以"用户目录是否还存在"作为该用户是否迁移完成的判据 |
| ✅ 迁移期间的并发写入（不停机迁移） | 迁移与线上 push 共享同一把按 `reader_id` 分片的 `asyncio.Lock`（§7.1），保证同一用户的"迁移中的文件读取"与"新 push 的落库"互斥；迁移只处理"迁移开始时刻已存在的文件"，迁移过程中产生的新 push 直接走 DB 路径，不会被迁移逻辑覆盖（迁移写入按 last-write-wins 规则 upsert，见 §7.1 第 3 点） |
| 评论被管理员屏蔽后用户重新编辑 | 状态从 `hidden` 按 `REVIEW_REQUIRES_APPROVAL` 规则重新判定为 `pending`/`approved`（见 §2.4d），不保留在 `hidden` |
| `review_banned=True` 的用户历史评论 | 保留展示（不因为封禁而隐藏历史内容），只是不能再新增/编辑 |

---

## 7. sync 服务落库与迁移方案

### 7.1 服务初始化时的一次性迁移（✅ 不停机执行）

- 触发时机：`MyReaderSyncService`（或专门的 `SyncMigrationService`）在进程启动时执行一次扫描迁移，接入 `main.py` 现有服务初始化流程。
- ✅ **不要求停机**：迁移与线上 push 共用按 `reader_id` 分片的 `asyncio.Lock`（`MyReaderSyncService._locks`），迁移某用户目录时持有该用户的锁，与该用户同时发起的 push 请求天然排队，不会互相踩踏；不同用户之间互不阻塞。
- 迁移单位：**按用户目录**处理，保证断点续迁移——扫描 `<MYREADER_SYNC_PATH>/` 下所有 `<uid>` 子目录，对每个 `uid`：
  1. 加该用户的锁。
  2. 遍历 `<uid>/<book_hash>/` 下的 `books.json`/`configs.json`/`notes.json`（存在才处理），逐条转换为 `ReadingRecord` 行：
     - 先用该目录名 `book_hash` 按 §5.2 规则算出 `book_id`（每个 `book_hash` 只需算一次，同目录下三个文件共用）
     - `books`/`configs`：整份 JSON 作为一条记录（`record_id = book_hash`）
     - `notes`：JSON 内以 `id` 为 key 的每一项拆成一条记录（`record_id = note.id`），检查 payload 是否已有 `uid`，没有则补上当前 `uid`
  3. 按 last-write-wins 规则 upsert（若该 `(reader_id, book_hash, kind, record_id)` 在库中已存在且 `updated_at` 更新，保留库里的，不用旧文件覆盖）。
  4. 该 `book_hash` 目录三个文件都处理完后，删除 `<uid>/<book_hash>/` 目录。
  5. 该 `uid` 下所有 `book_hash` 子目录处理完（目录已空）后，删除 `<uid>/` 目录。
  6. 释放锁。
- 断点续迁移：目录还在 = 还没迁移完，重启后重新扫描剩余目录即可继续；已完成的用户目录已不存在，不会重复处理。落库是幂等 upsert，即使"落库成功但删目录失败"导致重跑，也只是多一次无副作用写入。
- ✅ **迁移完成标记**：全局扫描一遍如果发现 `MYREADER_SYNC_PATH` 下已无任何 `<uid>` 子目录，把配置项 `SYNC_LEGACY_MIGRATION_DONE` 写为 `True`（通过项目现有的 `SettingsSaver` 落到 `auto.py`）；下次启动时若该配置已为 `True`，跳过扫描，直接用 DB 路径服务请求（除非该配置被手动重置为 `False`，用于故障排查时强制重新扫描）。

### 7.2 push/pull 逻辑改造

- 文件 IO 方法替换为 §4.3 的 `SyncWriteBuffer`（内存缓冲 + 定时批量 upsert 到 `reading_records`）与查询方法（优先读 §4.1 缓存，未命中查库）。
- push 时，`notes` 类每条 incoming 记录若没带 `uid`，补上 `payload["uid"] = uid`（当前登录用户）。
- `pull`/`push` 都支持 `own` 参数透传，具体见 §2.5 第 3 点。
- 按 `reader_id` 分片的锁保留，串行化"读取→合并→写入缓冲"；真正落库由 `SyncWriteBuffer` 的定时任务批量提交（一次事务）。

### 7.3 测试要点

- 全新用户（无历史文件）直接走 DB 路径
- 有历史文件的用户首次启动触发迁移，迁移后文件被删除，`SYNC_LEGACY_MIGRATION_DONE` 正确置位
- 迁移中断（模拟异常）后重启可续跑，不产生重复/丢失数据
- 迁移期间并发 push 同一用户同一本书，最终数据符合 last-write-wins
- `own=0/1` 两种查询结果差异，`ENABLE_SHARED_NOTES=False` 时 `own=0` 退化为只返回自己的
- notes 补 `uid` 的迁移与运行时两条路径都要测
- `SyncWriteBuffer` 的批量 flush：验证 flush 周期内多次更新只保留最后一次、flush 后 WS 广播才触发
- 计数器（`Item.count_*`）的懒回填、递减不为负
- `book_id` 提取：`cloud-<id>-<fmt>` 格式的 `book_hash` 能正确解析出正整数 `book_id`；非该格式（本地书籍）的 `book_hash` 得到稳定的负数占位值，且同一 `book_hash` 多次计算结果一致；跨用户共读查询正确按 `book_id > 0` 排除本地书籍

---

## 8. 决策记录（原"待确认问题清单"，逐条已确认）

> 以下问答为原始澄清过程存档；结论已回填进第 1–7 节正文，此处保留供追溯。

1. 评分量级：1–5 星还是沿用当前 `book.rating` 的 1–10（`length="10"`）刻度？
   **Answer：沿用现在 book.rating 的评分方式。**
2. "允许用户向别的用户推荐书籍"是否是独立功能？
   **Answer：这次先处理评分评论，评价即为推荐。**
3. 评论是否需要审核/举报/删除（管理员侧）机制？
   **Answer："浏览与阅读"中当允许用户评论时，增加设置项：评论需要审核后才能展示，默认关闭。1. 管理员可在书籍详情中对用户评论执行删除，效果是将评论状态改为隐藏。2. 用户管理中每个用户增加"禁止发表评论"操作，其它位置需判断当前用户是否被禁止评论；`user/info` 接口需增加评论权限状态。3. 系统管理中增加"用户评论"，表格分页展示书名、用户名、评分、评论内容和状态（未审核/通过/隐藏），操作按状态显示：未审核→通过/屏蔽，通过→隐藏，屏蔽→恢复。**
4. 用户级偏好设置存储位置？
   **Answer：增加独立列。**
5. 首页推荐卡片是否需要展示"推荐人"身份？
   **Answer：增加推荐用户的头像角标显示。**
6. 阅读信息统计条随主接口返回还是新开轻量接口？
   **Answer：增加一个轻量接口。**
7. "like icon"用什么图标？
   **Answer：大拇指。**
8. 评论是否允许为空？
   **Answer：允许。**
9. 是否需要"删除自己的评价"入口？
   **Answer：可以预留。**
10. "其它书籍"卡片具体指哪个区块？
    **Answer：两个都算，评论区在它们之上显示。**
11. 评论列表是否需要分页/"加载更多"？
    **Answer：需要分页，上方增加选择日期范围：一周内、一个月内、三个月内。**
12. 无人评价时"评论"卡片如何展示？
    **Answer：显示暂无评论。如果当前用户没有当前书籍的评论，卡片右侧显示一个 + 号按钮，效果与打开评价对话框一样，方便用户在这里添加评论。**
13. `own` 参数是否新增独立接口？
    **Answer：在当前 sync 接口上增加参数即可，由 `MyReaderSyncService` 来处理组装，sync 接口本身只是传参。**
14. sync 落库范围是否含 `books` 类？
    **Answer：一并迁移。**
15. `reading_records`（原 `sync_records`）是否需要结构化字段？
    **Answer：维持 payload JSON 形式即可。需要记录更新时间。表名改为 `reading_records`。**
16. 是否需要统一的轻量缓存工具？
    **Answer：可以引入一个通用工具。**
17. 阅读信息条计数是否采用计数器方案？
    **Answer：可以使用计数器方案。需要考虑到现有数据，计数需要增减变化，避免出现为负值的情况。或者在更新阅读状态时判断，如果对应计数字段不存在，就在阅读状态中统计一次更新进去。**
18. 共读场景单本书返回"他人笔记"数量上限与排序策略？
    **Answer：按更新时间排序，最多返回最近 20 个人的记录。**
19. `user_database` 类型与 sync 写入频率应对方案？
    **Answer：当前是 sqlite 数据库，做好队列控制，使用批量合并提交，来降低落库和查询频率（批量合并时，查询也可以通过缓存获取）。文档需要明确合并周期时长，以常量定义。**
20. 后端新增文案是否要走 i18n `.po` 编译流程？
    **Answer：后端先按中文处理，不需要走 i18n 的编译流程，后续再添加完整的多国语言支持。但是前端必须完整支持多国语言。**
21. 删除书籍时是否需要级联清理？表名是否调整？
    **Answer：需要对应清理。表名 `reader_book_reviews` 改为 `book_reviews`，同步记录也需要清理。**
22. sync 数据库迁移是否要求停机执行？
    **Answer：不能停机，用户可能发起新的 push。**
23. 迁移完成后是否需要标记？
    **Answer：可以在 settings 做一个记录。**

---

## 9. 建议的实施顺序

1. **Phase 0**：本文档 Review（已完成）
2. **Phase 1**：`reading_records` 表 + `SyncWriteBuffer` 批量落库 + 不停机迁移逻辑 + `own` 参数（在 `MyReaderSyncService` 内实现） —— "查看他人笔记"的数据基础
3. **Phase 2**：`book_reviews` 表 + 评价 CRUD 接口（含审核状态机）+ `Item` 表计数器扩展（含懒回填）+ 通用 `TTLCache` 工具
4. **Phase 3**：后台管理——"用户评论"管理页、用户管理页"禁止发表评论"、书籍详情管理员隐藏评论入口
5. **Phase 4**：前端——管理员设置项、用户设置项、书籍详情页三块 UI（统计条 / 评价入口 / 评论卡片，含分页与日期筛选、空态 + 号）
6. **Phase 5**：首页推荐位（含推荐人头像角标）
7. **Phase 6**：前端 i18n 全量补全（zh/zh-TW/en）、异常场景测试、性能验证（sync 批量写入压测、SQLite 锁争用观察）

每个 Phase 建议独立提测，避免大 PR 难以 review。Phase 1 与 Phase 2 可并行开发，Phase 3/4 依赖 Phase 2 的表结构和接口先落地。
