from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
import os
import requests
from enum import Enum

TODOIST_API_TOKEN = os.environ.get("TODOIST_API_TOKEN")
TODOIST_BASE_URL = "https://api.todoist.com/rest/v2"

app = FastAPI(title="Todoist Schedule Importer v3")


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
    section_name: Optional[str] = Field(
        default=None,
        description="Todoist 项目中的 section 名称，例如 'Monday'、'IELTS'；不存在时会自动创建"
    )
    duration_minutes: Optional[int] = Field(
        default=None,
        ge=1,
        description="任务持续时长（分钟），会映射到 Todoist 的 duration 字段"
    )
    due_lang: Optional[str] = Field(
        default=None,
        description="自然语言时间的语言代码，例如 'zh'（中文）、'en'（英文），提升 due_string 解析成功率"
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
    default_section_name: Optional[str] = Field(
        default=None,
        description="items 未指定 section_name 时的默认 section 名称"
    )
    layout_hint: Optional[str] = Field(
        default=None,
        description="布局提示（纯内部约定，用于指导 GPT 风格），例如：'by_weekday' / 'by_subject'"
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


# ---------- 查询任务相关模型 ----------

class TasksQuery(BaseModel):
    """
    查询任务的筛选条件
    """
    project_names: Optional[List[str]] = Field(
        default=None,
        description="要查询的项目名列表，例如 ['Schedule']；为空则查所有项目"
    )
    label_filters: Optional[List[str]] = Field(
        default=None,
        description="必须同时包含的标签名列表，例如 ['FMath', 'school']"
    )
    date_from: Optional[datetime] = Field(
        default=None,
        description="筛选 due 在这个时间之后的任务（含）"
    )
    date_to: Optional[datetime] = Field(
        default=None,
        description="筛选 due 在这个时间之前的任务（含）"
    )
    include_without_due: bool = Field(
        default=True,
        description="是否包含没有 due 的任务"
    )
    include_completed: bool = Field(
        default=False,
        description="是否包含已完成任务（当前实现仅支持未完成）"
    )
    timezone: str = Field(
        default="Asia/Singapore",
        description="用于把日期筛选统一到同一时区"
    )
    limit: int = Field(
        default=200,
        gt=0,
        le=1000,
        description="最多返回多少条任务，防止一次返回过多数据"
    )


class TaskSummary(BaseModel):
    """
    任务摘要信息
    """
    id: str
    content: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    section_id: Optional[str] = None
    section_name: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    priority: int = 1
    due_datetime: Optional[datetime] = None   # 有具体时间的
    due_date: Optional[date] = None           # 只有日期的
    raw_due_string: Optional[str] = None      # Todoist 的 due.string
    duration_minutes: Optional[int] = None
    is_completed: bool = False


class TasksQueryResponse(BaseModel):
    """
    查询任务的响应
    """
    tasks: List[TaskSummary]


# ---------- 空档计算相关模型 ----------

class FreeSlotRequest(BaseModel):
    """
    计算空档时间的请求
    """
    project_names: Optional[List[str]] = Field(
        default=None,
        description="主要用来找日程的项目，例如 ['Schedule', 'Study Blocks']"
    )
    label_filters: Optional[List[str]] = Field(
        default=None,
        description="把哪些标签视为'占用时间'的任务，例如 ['school', 'ielts']"
    )
    date_from: datetime = Field(..., description="空档搜索起点")
    date_to: datetime = Field(..., description="空档搜索终点")
    timezone: str = Field(
        default="Asia/Singapore",
        description="定义 date_from / date_to 所在时区"
    )
    workday_start: str = Field(
        default="08:00",
        description="每天视作可用时间的开始，例如 '08:00'"
    )
    workday_end: str = Field(
        default="23:00",
        description="每天视作可用时间的结束，例如 '23:00'"
    )
    min_slot_minutes: int = Field(
        default=45,
        description="认为是'有效空档'的最短时长"
    )


class FreeSlot(BaseModel):
    """
    一个空档时间段
    """
    start: datetime
    end: datetime


class FreeSlotResponse(BaseModel):
    """
    空档计算的响应
    """
    free_slots: List[FreeSlot]


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


def fetch_sections(project_id: str) -> Dict[str, str]:
    """
    拉取某个项目下的所有 sections，返回 {section名: id}
    """
    resp = requests.get(
        f"{TODOIST_BASE_URL}/sections",
        headers=todoist_headers(),
        params={"project_id": project_id},
        timeout=15,
    )
    resp.raise_for_status()
    sections = resp.json()
    return {s["name"]: s["id"] for s in sections}


def get_or_create_section(name: str, project_id: str, section_map: Dict[str, str]) -> str:
    """
    获取 section ID；如果没有就在指定项目下创建
    """
    if name in section_map:
        return section_map[name]

    resp = requests.post(
        f"{TODOIST_BASE_URL}/sections",
        headers=todoist_headers(),
        json={"name": name, "project_id": project_id},
        timeout=15,
    )
    resp.raise_for_status()
    section = resp.json()
    section_map[section["name"]] = section["id"]
    return section["id"]


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
    - 如果给了 due_string，就直接用（支持 due_lang 指定语言）
    - 否则如果给了 start_datetime，就用 datetime + timezone
    """
    if item.due_string:
        due_obj = {"string": item.due_string}
        if item.due_lang:
            due_obj["lang"] = item.due_lang
        return due_obj

    if item.start_datetime:
        tz = item.timezone or tz_default
        iso = item.start_datetime.isoformat()
        return {"datetime": iso, "timezone": tz}

    return None


# ---------- 主接口 ----------

@app.get("/")
def health_check():
    """
    健康检查端点，用于 Render 等平台的部署验证
    """
    return {
        "status": "healthy",
        "service": "Todoist Schedule Importer v3",
        "version": "3.0.0"
    }


@app.post("/import_schedule_to_todoist", response_model=ImportResponse)
def import_schedule(body: ImportRequest):
    """
    把一组课表 items 批量导入 Todoist，支持：
    - mode=create：只追加
    - mode=replace_project：清空某项目后重建
    - dry_run：只模拟，不真正写入 Todoist
    - 默认项目 / 标签 / 优先级 / 时区 / section
    - 标题统一前后缀
    - section 分组（自动创建 section）
    - duration 时长设置
    - due_lang 自然语言时间解析（支持中文）
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

            # 1.5. 处理 section（需要先有 project_id）
            section_id = None
            if project_id:
                effective_section_name = item.section_name or options.default_section_name
                if effective_section_name:
                    # 获取该项目的 section 映射（为避免频繁请求，可优化为按项目缓存）
                    try:
                        section_map = fetch_sections(project_id)
                        section_id = get_or_create_section(
                            effective_section_name, project_id, section_map
                        )
                    except requests.RequestException as e:
                        # Section 创建失败不影响任务创建，记录但继续
                        pass

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
            if section_id:
                payload["section_id"] = section_id
            if label_ids:
                payload["labels"] = label_ids
            if due:
                payload["due"] = due
            if item.duration_minutes:
                payload["duration"] = item.duration_minutes
                payload["duration_unit"] = "minute"

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


# ---------- 查询任务接口 ----------

def fetch_tasks_from_todoist(project_id: Optional[str] = None) -> List[dict]:
    """
    从 Todoist 获取任务列表
    """
    headers = todoist_headers()
    params = {}
    if project_id:
        params["project_id"] = project_id
    
    resp = requests.get(
        f"{TODOIST_BASE_URL}/tasks",
        headers=headers,
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def parse_task_due(due_obj: Optional[dict]) -> tuple:
    """
    解析 Todoist 任务的 due 字段
    返回 (due_datetime, due_date, raw_due_string)
    """
    if not due_obj:
        return None, None, None
    
    raw_string = due_obj.get("string")
    
    # 如果有 datetime 字段（带时间）
    if "datetime" in due_obj and due_obj["datetime"]:
        try:
            dt = datetime.fromisoformat(due_obj["datetime"].replace("Z", "+00:00"))
            return dt, None, raw_string
        except:
            pass
    
    # 如果只有 date 字段（只有日期）
    if "date" in due_obj and due_obj["date"]:
        try:
            d = datetime.strptime(due_obj["date"], "%Y-%m-%d").date()
            return None, d, raw_string
        except:
            pass
    
    return None, None, raw_string


@app.post("/query_tasks", response_model=TasksQueryResponse)
def query_tasks(query: TasksQuery):
    """
    查询 Todoist 任务列表，支持：
    - 按项目名筛选
    - 按标签筛选
    - 按时间范围筛选
    - 限制返回数量
    """
    try:
        # 1. 获取项目和标签映射
        project_map = fetch_projects()  # {name: id}
        label_map = fetch_labels()      # {name: id}
        
        # 创建反向映射
        project_id_to_name = {v: k for k, v in project_map.items()}
        label_id_to_name = {v: k for k, v in label_map.items()}
        
        # 2. 确定要查询的项目
        project_ids_to_query = []
        if query.project_names:
            for name in query.project_names:
                if name in project_map:
                    project_ids_to_query.append(project_map[name])
        else:
            # 查询所有项目
            project_ids_to_query = list(project_map.values()) if project_map else [None]
        
        # 3. 获取所有任务
        all_tasks = []
        if not project_ids_to_query:
            # 如果没有指定项目，查所有
            all_tasks = fetch_tasks_from_todoist()
        else:
            for pid in project_ids_to_query:
                tasks = fetch_tasks_from_todoist(pid)
                all_tasks.extend(tasks)
        
        # 4. 获取所有相关项目的 section 映射
        section_cache = {}  # {project_id: {section_id: section_name}}
        for task in all_tasks:
            pid = task.get("project_id")
            if pid and pid not in section_cache:
                try:
                    sections = fetch_sections(pid)  # {name: id}
                    section_cache[pid] = {v: k for k, v in sections.items()}  # {id: name}
                except:
                    section_cache[pid] = {}
        
        # 5. 过滤和转换任务
        results = []
        for task in all_tasks:
            # 解析标签
            task_label_ids = task.get("labels", [])
            task_label_names = [label_id_to_name.get(lid, lid) for lid in task_label_ids]
            
            # 标签过滤
            if query.label_filters:
                if not all(label in task_label_names for label in query.label_filters):
                    continue
            
            # 解析 due
            due_datetime, due_date, raw_due_string = parse_task_due(task.get("due"))
            
            # 时间范围过滤
            if query.date_from or query.date_to:
                task_time = due_datetime or (datetime.combine(due_date, datetime.min.time()) if due_date else None)
                
                if not task_time:
                    if not query.include_without_due:
                        continue
                else:
                    if query.date_from and task_time < query.date_from:
                        continue
                    if query.date_to and task_time > query.date_to:
                        continue
            elif not (due_datetime or due_date) and not query.include_without_due:
                continue
            
            # 获取 section 名称
            section_id = task.get("section_id")
            section_name = None
            if section_id:
                pid = task.get("project_id")
                if pid in section_cache:
                    section_name = section_cache[pid].get(section_id)
            
            # 解析 duration
            duration_minutes = None
            if task.get("duration"):
                amount = task["duration"].get("amount")
                unit = task["duration"].get("unit")
                if amount and unit == "minute":
                    duration_minutes = amount
            
            # 构造 TaskSummary
            summary = TaskSummary(
                id=str(task["id"]),
                content=task["content"],
                description=task.get("description"),
                project_id=task.get("project_id"),
                project_name=project_id_to_name.get(task.get("project_id")),
                section_id=section_id,
                section_name=section_name,
                labels=task_label_names,
                priority=task.get("priority", 1),
                due_datetime=due_datetime,
                due_date=due_date,
                raw_due_string=raw_due_string,
                duration_minutes=duration_minutes,
                is_completed=task.get("is_completed", False)
            )
            results.append(summary)
            
            # 限制数量
            if len(results) >= query.limit:
                break
        
        # 6. 按时间排序
        def sort_key(t: TaskSummary):
            if t.due_datetime:
                return (0, t.due_datetime)
            elif t.due_date:
                return (1, datetime.combine(t.due_date, datetime.min.time()))
            else:
                return (2, datetime.max)
        
        results.sort(key=sort_key)
        
        return TasksQueryResponse(tasks=results)
    
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to query Todoist tasks: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing query: {e}"
        )


# ---------- 空档计算接口 ----------

@app.post("/free_slots", response_model=FreeSlotResponse)
def compute_free_slots(request: FreeSlotRequest):
    """
    计算指定时间范围内的空档时间，支持：
    - 按项目和标签筛选"占用时间"的任务
    - 设置每天可用时间范围（workday_start ~ workday_end）
    - 过滤最小空档时长
    """
    try:
        # 1. 先用内部的 query_tasks 获取所有占用时间的任务
        query = TasksQuery(
            project_names=request.project_names,
            label_filters=request.label_filters,
            date_from=request.date_from,
            date_to=request.date_to,
            include_without_due=False,  # 空档计算只看有时间的任务
            timezone=request.timezone,
            limit=1000
        )
        
        tasks_response = query_tasks(query)
        
        # 2. 把任务转换成忙碌时间段
        busy_intervals = []
        for task in tasks_response.tasks:
            if not task.due_datetime:
                continue  # 只处理有具体时间的任务
            
            start = task.due_datetime
            
            # 计算结束时间
            if task.duration_minutes:
                end = start + timedelta(minutes=task.duration_minutes)
            else:
                # 默认假设 1 小时
                end = start + timedelta(hours=1)
            
            busy_intervals.append((start, end))
        
        # 3. 按开始时间排序
        busy_intervals.sort(key=lambda x: x[0])
        
        # 4. 解析工作时间
        try:
            work_start_hour, work_start_min = map(int, request.workday_start.split(":"))
            work_end_hour, work_end_min = map(int, request.workday_end.split(":"))
        except:
            raise HTTPException(
                status_code=400,
                detail="Invalid workday_start or workday_end format. Use 'HH:MM'"
            )
        
        # 5. 按天扫描空档
        free_slots = []
        current_date = request.date_from.date()
        end_date = request.date_to.date()
        
        while current_date <= end_date:
            # 当天的工作时间范围
            day_start = datetime.combine(
                current_date,
                datetime.min.time().replace(hour=work_start_hour, minute=work_start_min)
            )
            day_end = datetime.combine(
                current_date,
                datetime.min.time().replace(hour=work_end_hour, minute=work_end_min)
            )
            
            # 筛选当天的忙碌区间
            day_busy = [
                (max(start, day_start), min(end, day_end))
                for start, end in busy_intervals
                if start.date() == current_date and end > day_start and start < day_end
            ]
            
            # 合并重叠的忙碌区间
            if day_busy:
                day_busy.sort(key=lambda x: x[0])
                merged = [day_busy[0]]
                for start, end in day_busy[1:]:
                    last_start, last_end = merged[-1]
                    if start <= last_end:
                        # 重叠，合并
                        merged[-1] = (last_start, max(last_end, end))
                    else:
                        merged.append((start, end))
                day_busy = merged
            
            # 计算空档
            current_time = day_start
            for busy_start, busy_end in day_busy:
                if current_time < busy_start:
                    # 有空档
                    gap_minutes = (busy_start - current_time).total_seconds() / 60
                    if gap_minutes >= request.min_slot_minutes:
                        free_slots.append(FreeSlot(start=current_time, end=busy_start))
                current_time = max(current_time, busy_end)
            
            # 最后一个忙碌区间后到工作日结束
            if current_time < day_end:
                gap_minutes = (day_end - current_time).total_seconds() / 60
                if gap_minutes >= request.min_slot_minutes:
                    free_slots.append(FreeSlot(start=current_time, end=day_end))
            
            current_date += timedelta(days=1)
        
        return FreeSlotResponse(free_slots=free_slots)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error computing free slots: {e}"
        )
