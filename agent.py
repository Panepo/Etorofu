import os
import time
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from dotenv import load_dotenv

load_dotenv()

# --- Ollama 配置 ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:8088")

# --- 模型混合配置 ---
MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST")    # 快速，適合反覆搜尋
MODEL_SMART = os.getenv("OLLAMA_MODEL_SMART")   # 強大，適合內容創作與校對


@tool("DuckDuckGo Search")
def duckduckgo_search(query: str) -> str:
    """Searches the web using DuckDuckGo and returns the top results."""
    return DuckDuckGoSearchRun().run(query)


def generate_tags(content: str, llm) -> str:
    """Use LLM to extract comma-separated keywords/tags from report content."""
    prompt = f"""以下是一篇研究報告的內容。請從中提取 5 到 8 個最具代表性的關鍵字或標籤，用於搜尋與分類。
請只回傳以逗號分隔的關鍵字列表，不要有任何其他說明文字或標點符號。

報告內容：
{content[:3000]}
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    # Strip whitespace and any surrounding quotes
    return response.content.strip().strip('"').strip("'")


def run_knowledge_extraction(task_id: str, topic: str, tasks_db: dict):
    try:
        # ChatOllama instances for direct LangChain calls (e.g. generate_tags)
        fast_chat = ChatOllama(base_url=OLLAMA_URL, model=MODEL_FAST, temperature=0.5)

        # CrewAI LLM instances for agents
        fast_llm = LLM(model=f"ollama/{MODEL_FAST}", base_url=OLLAMA_URL, temperature=0.5)
        smart_llm = LLM(model=f"ollama/{MODEL_SMART}", base_url=OLLAMA_URL, temperature=0.7)

        # 1. 研究員 (使用快速模型)
        tasks_db[task_id]["status"] = "searching"
        researcher = Agent(
            role='資深情報分析員',
            goal=f'搜集關於 {topic} 的最新事實、數據與趨勢',
            backstory="你擅長在大量網路資訊中過濾出最有價值的核心情報。",
            tools=[duckduckgo_search],
            llm=fast_llm,
            verbose=True
        )

        # 2. 作家與編輯 (使用強大模型)
        writer = Agent(
            role='科技專欄作家',
            goal='將研究資料轉化為結構嚴謹的繁體中文 Markdown 報告',
            backstory="你以文筆洗鍊、邏輯清晰著稱，能將技術細節寫得生動易懂。",
            llm=smart_llm,
            verbose=True
        )

        editor = Agent(
            role='總編輯',
            goal='校對並優化報告，確保語氣專業、排版精美且無錯別字',
            backstory="你是完美的守門人，負責確保報告完全符合專業繁體中文標準。",
            llm=smart_llm,
            verbose=True
        )

        # 定義任務流程
        t1 = Task(description=f"深度搜尋 {topic} 並整理成事實清單。", expected_output="事實筆記", agent=researcher)
        t2 = Task(description="根據筆記撰寫初稿。", expected_output="Markdown草稿", agent=writer)
        t3 = Task(description="進行最終審核與語法修飾。", expected_output="最終版報告", agent=editor)

        # 執行 Crew
        tasks_db[task_id]["status"] = "writing"
        crew = Crew(
            agents=[researcher, writer, editor],
            tasks=[t1, t2, t3],
            process=Process.sequential
        )

        result = crew.kickoff()
        result_str = str(result)

        # 生成標籤
        tasks_db[task_id]["status"] = "tagging"
        tags = generate_tags(result_str, fast_chat)

        tasks_db[task_id]["status"] = "completed"
        tasks_db[task_id]["result"] = result_str
        tasks_db[task_id]["tags"] = tags
        tasks_db[task_id]["completed_at"] = time.time()

    except Exception as e:
        tasks_db[task_id]["status"] = "failed"
        tasks_db[task_id]["error"] = str(e)
