from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
import os
import requests
from enum import Enum

TODOIST_API_TOKEN = os.environ.get("TODOIST_API_TOKEN")
TODOIST_BASE_URL = "https://api.todoist.com/rest/v2"

app = FastAPI(title="Todoist Schedule Importer v2")


# ---------- 数据模型 ----------

class ScheduleItem(BaseModel):
    """
    单条课 / 时间块 -> 一条 Todoist 任务
    """
    title: str = Field(..., description="任务标题或课程名，例如 'A2-1 Further Math'")
    description: Optional[str] = Field(
        default=None,
        description="备注，比如教室、老师、上课方式等"
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Todoist 里的项目名；如果不存在会自动创建"
    )
    labels: List[str] = Field(
        default_factory=list,
        description="标签名列表；不存在的会自动创建"
    )
    priority: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Todoist 优先级 1~4，4 最高"
    )
    due_string: Optional[str] = Field(
        default=None,
        description="Todoist 的自然语言时间，例如 'every Monday at 9:00'"
    )
    start_datetime: Optional[datetime] = Field(
        default=None,
        description="开始时间（ISO 字符串），例如 '2025-11-18T09:00:00+08:00'"
    )
    end_datetime: Optional[datetime] = Field(
        default=None,
        description="结束时间（ISO 字符串），会写进 description 方便你看"
    )
    timezone: Optional[str] = Field(
        default=None,
        description="时区，比如 'Asia/Singapore'"
    )


class ImportMode(str, Enum):
    CREATE = "create"
    REPLACE_PROJECT = "replace_project"


class ImportOptions(BaseModel):
    """
    控制导入行为的全局选项
    """
    mode: ImportMode = Field(
        default=ImportMode.CREATE,
        description="导入模式：create=只追加任务；replace_project=清空某项目后再创建"
    )
    replace_project_name: Optional[str] = Field(
        default=None,
        description="当 mode=replace_project 时，要被清空并重建的项目名"
    )
    dry_run: bool = Field(
        default=False,
        description="如果为 True，则不真正调用 Todoist，只返回模拟结果"
    )
    default_project_name: Optional[str] = Field(
        default=None,
        description="items 里未指定 project_name 时的默认项目名"
    )
    default_labels: List[str] = Field(
        default_factory=list,
        description="items 里未指定 labels 时的默认标签列表"
    )
    default_priority: int = Field(
        default=1,
        ge=1,
        le=4,
        description="items 未设置 priority 时的默认优先级（1~4）"
    )
    default_timezone: str = Field(
        default="Asia/Singapore",
        description="items 未设置 timezone 时的默认时区"
    )
    title_prefix: Optional[str] = Field(
        default=None,
        description="给所有任务标题统一加的前缀，例如 '[课表] '"
    )
    title_suffix: Optional[str] = Field(
        default=None,
        description="给所有任务标题统一加的后缀"
    )


class ImportRequest(BaseModel):
    items: List[ScheduleItem] = Field(..., min_items=1)
    options: Optional[ImportOptions] = Field(
        default=None,
        description="导入行为的全局选项，可为空"
    )


class CreatedTask(BaseModel):
    index: int
    task_id: str
    content: str
    project_id: Optional[str] = None
    dry_run: bool = False


class ErrorInfo(BaseModel):
    index: int
    message: str


class ImportResponse(BaseModel):
    created: List[CreatedTask]
    errors: List[ErrorInfo]


# ---------- Todoist 帮助函数 ----------

def todoist_headers() -> Dict[str, str]:
    """
    构造 Todoist 请求头
    """
    if not TODOIST_API_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="TODOIST_API_TOKEN environment variable is not set."
        )
    return {
        "Authorization": f"Bearer {TODOIST_API_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_projects() -> Dict[str, str]:
    """
    拉取所有项目，返回 {项目名: id}
    """
    resp = requests.get(
        f"{TODOIST_BASE_URL}/projects",
        headers=todoist_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    projects = resp.json()
    return {p["name"]: p["id"] for p in projects}


def fetch_labels() -> Dict[str, str]:
    """
    拉取所有标签，返回 {标签名: id}
    """
    resp = requests.get(
        f"{TODOIST_BASE_URL}/labels",
        headers=todoist_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    labels = resp.json()
    return {l["name"]: l["id"] for l in labels}


def get_or_create_project(name: str, project_map: Dict[str, str]) -> str:
    """
    获取项目 ID；如果没有就创建
    """
    if name in project_map:
        return project_map[name]

    resp = requests.post(
        f"{TODOIST_BASE_URL}/projects",
        headers=todoist_headers(),
        json={"name": name},
        timeout=15,
    )
    resp.raise_for_status()
    project = resp.json()
    project_map[project["name"]] = project["id"]
    return project["id"]


def get_or_create_label(name: str, label_map: Dict[str, str]) -> str:
    """
    获取标签 ID；如果没有就创建
    """
    if name in label_map:
        return label_map[name]

    resp = requests.post(
        f"{TODOIST_BASE_URL}/labels",
        headers=todoist_headers(),
        json={"name": name},
        timeout=15,
    )
    resp.raise_for_status()
    label = resp.json()
    label_map[label["name"]] = label["id"]
    return label["id"]


def clear_project_tasks(project_id: str):
    """
    清空某项目下的所有未完成任务
    """
    resp = requests.get(
        f"{TODOIST_BASE_URL}/tasks",
        headers=todoist_headers(),
        params={"project_id": project_id},
        timeout=20,
    )
    resp.raise_for_status()
    tasks = resp.json()

    for t in tasks:
        task_id = t["id"]
        del_resp = requests.delete(
            f"{TODOIST_BASE_URL}/tasks/{task_id}",
            headers=todoist_headers(),
            timeout=15,
        )
        # 单个删除失败就跳过，避免全局中断
        if del_resp.status_code not in (200, 204):
            continue


def build_due(item: ScheduleItem, tz_default: str) -> Optional[dict]:
    """
    构造 Todoist 的 due 字段：
    - 如果给了 due_string，就直接用
    - 否则如果给了 start_datetime，就用 datetime + timezone
    """
    if item.due_string:
        return {"string": item.due_string}

    if item.start_datetime:
        tz = item.timezone or tz_default
        iso = item.start_datetime.isoformat()
        return {"datetime": iso, "timezone": tz}

    return None


# ---------- 主接口 ----------

@app.post("/import_schedule_to_todoist", response_model=ImportResponse)
def import_schedule(body: ImportRequest):
    """
    把一组课表 items 批量导入 Todoist，支持：
    - mode=create：只追加
    - mode=replace_project：清空某项目后重建
    - dry_run：只模拟，不真正写入 Todoist
    - 默认项目 / 标签 / 优先级 / 时区
    - 标题统一前后缀
    """
    headers = todoist_headers()

    # 如果 options 为空，就使用 ImportOptions 的默认配置
    options = body.options or ImportOptions()
    created: List[CreatedTask] = []
    errors: List[ErrorInfo] = []

    # 先获取现有项目和标签映射
    try:
        project_map = fetch_projects()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch Todoist projects: {e}"
        )

    try:
        label_map = fetch_labels()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch Todoist labels: {e}"
        )

    # 如果是 replace_project 模式，且指定了 replace_project_name，则先清空项目
    target_project_id_for_replace: Optional[str] = None
    if options.mode == ImportMode.REPLACE_PROJECT and options.replace_project_name:
        try:
            target_project_id_for_replace = get_or_create_project(
                options.replace_project_name, project_map
            )
            if not options.dry_run:
                clear_project_tasks(target_project_id_for_replace)
        except requests.RequestException as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to prepare project for replace_project mode: {e}"
            )

    for idx, item in enumerate(body.items):
        try:
            # 1. 计算最终项目名
            effective_project_name = (
                item.project_name
                or options.default_project_name
                or item.project_name  # 防止都为空，保持旧逻辑
            )

            # replace_project 模式下，强制把所有任务打到同一个项目里
            if options.mode == ImportMode.REPLACE_PROJECT and options.replace_project_name:
                effective_project_name = options.replace_project_name

            project_id = None
            if effective_project_name:
                project_id = get_or_create_project(effective_project_name, project_map)

            # 2. 合并标签：item.labels + default_labels 去重
            all_labels = list(
                dict.fromkeys((options.default_labels or []) + (item.labels or []))
            )
            label_ids: List[str] = []
            for name in all_labels:
                label_ids.append(get_or_create_label(name, label_map))

            # 3. 时间
            tz_default = options.default_timezone or "Asia/Singapore"
            due = build_due(item, tz_default)

            # 4. description，把时间块写进去方便你查看
            desc_parts = []
            if item.description:
                desc_parts.append(item.description)

            if item.start_datetime or item.end_datetime:
                time_str = "Time block: "
                if item.start_datetime:
                    time_str += item.start_datetime.isoformat()
                if item.end_datetime:
                    time_str += " ~ " + item.end_datetime.isoformat()
                desc_parts.append(time_str)

            description = "\n".join(desc_parts) if desc_parts else ""

            # 5. 标题前后缀
            title = item.title
            if options.title_prefix:
                title = f"{options.title_prefix}{title}"
            if options.title_suffix:
                title = f"{title}{options.title_suffix}"

            # 6. 拼 Todoist 任务 payload
            payload = {
                "content": title,
                "priority": item.priority or options.default_priority or 1,
            }
            if description:
                payload["description"] = description
            if project_id:
                payload["project_id"] = project_id
            if label_ids:
                payload["labels"] = label_ids
            if due:
                payload["due"] = due

            # dry_run：只返回"会创建什么"，不真正写入
            if options.dry_run:
                created.append(
                    CreatedTask(
                        index=idx,
                        task_id="dry-run",
                        content=title,
                        project_id=project_id,
                        dry_run=True,
                    )
                )
                continue

            # 7. 创建任务
            resp = requests.post(
                f"{TODOIST_BASE_URL}/tasks",
                headers=headers,
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            task = resp.json()

            created.append(
                CreatedTask(
                    index=idx,
                    task_id=str(task["id"]),
                    content=task["content"],
                    project_id=task.get("project_id"),
                    dry_run=False,
                )
            )

        except requests.RequestException as e:
            errors.append(
                ErrorInfo(index=idx, message=f"Todoist error: {e}")
            )
        except Exception as e:
            errors.append(
                ErrorInfo(index=idx, message=f"Unexpected error: {e}")
            )

    return ImportResponse(created=created, errors=errors)
