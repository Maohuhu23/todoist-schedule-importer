# Todoist Schedule Importer v2

这是一个基于 **Python + FastAPI** 的 serverless 风格服务，用于批量将结构化课表或时间块导入到 Todoist 任务管理系统。

## 项目简介

本服务提供一个 REST API 接口 `POST /import_schedule_to_todoist`，可以：

- 📚 批量导入课表/时间块到 Todoist
- 🏷️ 自动创建项目（Project）和标签（Label）
- 🔄 支持两种导入模式：
  - `create`：追加任务
  - `replace_project`：清空指定项目后重建整个课表
- 🧪 支持 `dry_run` 模式，模拟导入而不真正写入
- ⚙️ 灵活的全局选项：默认项目/标签/优先级/时区、标题前后缀等
- 🤖 完美适配 ChatGPT GPT Actions，让 AI 帮你解析课表并自动导入

## 本地运行步骤

### 1. 创建虚拟环境（可选但推荐）

```bash
cd todoist-schedule-importer
python3 -m venv .venv
source .venv/bin/activate  # Windows 用户使用: .venv\Scripts\activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 设置环境变量

你需要从 Todoist 获取 API Token：

1. 访问 [Todoist Settings → Integrations → Developer](https://app.todoist.com/app/settings/integrations/developer)
2. 复制你的 **API Token**
3. 在终端中设置环境变量：

```bash
export TODOIST_API_TOKEN="你的_Todoist_API_Token"
```

**Windows PowerShell 用户：**
```powershell
$env:TODOIST_API_TOKEN="你的_Todoist_API_Token"
```

### 4. 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

服务将在 `http://localhost:8000` 启动。

你可以访问 `http://localhost:8000/docs` 查看自动生成的 API 文档（Swagger UI）。

### 5. 测试接口

使用 `curl` 测试导入功能：

```bash
curl -X POST "http://localhost:8000/import_schedule_to_todoist" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {
        "title": "A2-1 Further Math",
        "description": "教室：A203，老师：张老师",
        "project_name": "课表",
        "labels": ["A2-1", "Math"],
        "priority": 2,
        "due_string": "every Monday at 9:00"
      },
      {
        "title": "Physics Lab",
        "description": "实验室 B101",
        "project_name": "课表",
        "labels": ["A2-1", "Physics"],
        "priority": 3,
        "start_datetime": "2025-11-18T14:00:00+08:00",
        "end_datetime": "2025-11-18T16:00:00+08:00",
        "timezone": "Asia/Singapore"
      }
    ],
    "options": {
      "mode": "create",
      "dry_run": false,
      "title_prefix": "[课表] "
    }
  }'
```

**Dry Run 测试（不真正写入）：**

```bash
curl -X POST "http://localhost:8000/import_schedule_to_todoist" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {
        "title": "测试课程",
        "project_name": "测试项目",
        "labels": ["测试"],
        "due_string": "tomorrow at 10:00"
      }
    ],
    "options": {
      "dry_run": true
    }
  }'
```

---

## 部署到 Render

### 前置准备

1. 确保你已经将代码推送到 GitHub 仓库
2. 注册 [Render](https://render.com/) 账号（免费计划即可）

### 部署步骤

1. **登录 Render 控制台**
   - 访问 https://dashboard.render.com/

2. **创建新的 Web Service**
   - 点击 "New +" → "Web Service"
   - 选择 "Build and deploy from a Git repository"
   - 连接你的 GitHub 账号并选择 `todoist-schedule-importer` 仓库

3. **配置服务**
   - **Name**: `todoist-schedule-importer`（可自定义）
   - **Region**: 选择离你最近的区域（如 Singapore）
   - **Branch**: `main`
   - **Root Directory**: 留空（如果项目在仓库根目录）
   - **Runtime**: `Python 3`
   - **Build Command**: 
     ```
     pip install -r requirements.txt
     ```
   - **Start Command**: 
     ```
     uvicorn main:app --host 0.0.0.0 --port $PORT
     ```

4. **添加环境变量**
   - 在 "Environment" 部分点击 "Add Environment Variable"
   - **Key**: `TODOIST_API_TOKEN`
   - **Value**: 你的 Todoist API Token（从 Todoist Settings → Integrations → Developer 获取）

5. **选择计划并部署**
   - 免费计划（Free）即可满足基本需求
   - 点击 "Create Web Service"
   - Render 会自动构建并部署你的应用

6. **获取服务 URL**
   - 部署成功后，你会得到一个类似 `https://todoist-schedule-importer-xxxx.onrender.com` 的 URL
   - **记下这个 URL，后面配置 GPT Actions 时会用到**

### 注意事项

- Render 免费计划在 15 分钟无活动后会自动休眠，首次访问可能需要 30-60 秒唤醒
- 如果需要始终在线，可以升级到付费计划（$7/月起）
- 建议设置 Health Check 路径为 `/docs`（Render 会自动检测服务可用性）

---

## 在 ChatGPT GPT Builder 中配置 Action

### 步骤概览

1. **进入 GPT Builder**
   - 访问 [ChatGPT](https://chat.openai.com/)
   - 点击你的头像 → "My GPTs" → "Create a GPT"

2. **配置 GPT 基本信息**
   - 在 "Configure" 标签页中：
     - **Name**: `Todoist 课表助手`（可自定义）
     - **Description**: `帮我把课表导入 Todoist`
     - **Instructions**: 可以写类似这样的提示词：
       ```
       你是一个课表导入助手。当用户提供课表信息（文字、截图或文件）时，
       你需要：
       1. 解析出每一节课的信息（课程名、时间、地点、老师等）
       2. 将它们转换成结构化的 JSON 格式
       3. 调用 importScheduleToTodoist action 将课表导入到用户的 Todoist
       4. 向用户确认导入结果
       
       支持的时间格式包括：
       - 自然语言："every Monday at 9:00"
       - ISO 8601 日期时间："2025-11-18T09:00:00+08:00"
       
       默认时区为 Asia/Singapore，优先级默认为 2。
       ```

3. **添加 Action**
   - 切换到 "Actions" 标签页
   - 点击 "Create new action"
   - 选择 "Import from URL" 或 "Use an OpenAPI schema"

4. **导入 OpenAPI Schema**
   - **方式 1：直接粘贴 JSON**（推荐）
     - 复制下方的 `openapi.json` 文件内容
     - 粘贴到 Schema 输入框中
     - **重要：** 将 `"url": "https://你的服务.onrender.com"` 替换为你在 Render 上实际获得的 URL
   
   - **方式 2：从 URL 导入**
     - 如果你把 `openapi.json` 托管在了某个公开 URL 上，可以直接填写 URL

5. **测试 Action**
   - 保存后，在 GPT 对话中测试：
     ```
     请帮我导入以下课表：
     - 周一 9:00-11:00 A2-1 Further Math，教室 A203
     - 周三 14:00-16:00 Physics Lab，实验室 B101
     ```
   - GPT 会解析课表并调用 API 导入到你的 Todoist

6. **发布 GPT**
   - 测试无误后，点击右上角 "Save" 或 "Publish"
   - 选择分享范围（Only me / Anyone with a link / Public）

### OpenAPI Schema 说明

完整的 OpenAPI JSON Schema 已保存在项目根目录的 `openapi.json` 文件中。

**使用前请务必替换以下内容：**

- `"url": "https://你的服务.onrender.com"` → 改为你在 Render 上部署后获得的真实 URL

---

## API 接口说明

### `POST /import_schedule_to_todoist`

**请求体结构：**

```json
{
  "items": [
    {
      "title": "课程名称",
      "description": "备注信息（可选）",
      "project_name": "项目名（可选）",
      "labels": ["标签1", "标签2"],
      "priority": 2,
      "due_string": "every Monday at 9:00",
      "start_datetime": "2025-11-18T09:00:00+08:00",
      "end_datetime": "2025-11-18T11:00:00+08:00",
      "timezone": "Asia/Singapore"
    }
  ],
  "options": {
    "mode": "create",
    "dry_run": false,
    "default_project_name": "课表",
    "default_labels": ["学校"],
    "default_priority": 2,
    "default_timezone": "Asia/Singapore",
    "title_prefix": "[课表] ",
    "title_suffix": ""
  }
}
```

**响应体结构：**

```json
{
  "created": [
    {
      "index": 0,
      "task_id": "7654321",
      "content": "[课表] 课程名称",
      "project_id": "123456",
      "dry_run": false
    }
  ],
  "errors": []
}
```

---

## 常见问题

### Q: 如何获取 Todoist API Token？
A: 访问 [Todoist Settings → Integrations → Developer](https://app.todoist.com/app/settings/integrations/developer)，复制 API Token。

### Q: Render 免费计划有什么限制？
A: 服务在 15 分钟无活动后会休眠，首次访问需要唤醒（30-60 秒）。每月有 750 小时免费运行时间（足够个人使用）。

### Q: 如何测试而不真正导入？
A: 在 `options` 中设置 `"dry_run": true`，服务会返回模拟结果，不会真正写入 Todoist。

### Q: 可以一次性替换整个项目的课表吗？
A: 可以！设置 `"mode": "replace_project"` 和 `"replace_project_name": "项目名"`，服务会先清空该项目的所有任务，然后重新导入。

### Q: 支持哪些时间格式？
A: 支持两种方式：
1. **自然语言**（`due_string`）：`"every Monday at 9:00"`、`"tomorrow at 14:00"` 等
2. **ISO 8601 日期时间**（`start_datetime`）：`"2025-11-18T09:00:00+08:00"`

---

## 开发与贡献

欢迎提交 Issue 和 Pull Request！

### 项目结构

```
todoist-schedule-importer/
├── main.py              # FastAPI 应用主文件
├── requirements.txt     # Python 依赖
├── .gitignore          # Git 忽略规则
├── README.md           # 项目说明（本文件）
└── openapi.json        # OpenAPI Schema（供 GPT Actions 使用）
```

### 本地开发建议

- 使用虚拟环境隔离依赖
- 代码风格：遵循 PEP 8
- 测试：可以用 `pytest` 编写单元测试

---

## 许可证

MIT License

---

## 联系方式

如有问题或建议，欢迎通过 GitHub Issues 联系。
