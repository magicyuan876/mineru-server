import base64
import hashlib
import os
import queue
import threading
import time
from typing import Optional

import uvicorn
from aiohttp.web_fileresponse import FileResponse
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Form, Query, HTTPException
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware
from starlette.status import HTTP_404_NOT_FOUND

import Pdf2MD
from SQLiteManager import SQLiteORM

# 数据库文件路径
db_file = 'minerU-server.db'

# 创建表的SQL语句
sql_create_users_table = """
CREATE TABLE IF NOT EXISTS file_task (
    task_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    md_file_path TEXT,
    status TEXT
);
"""

# 实例化 SQLiteManager
db = SQLiteORM(db_file)

# 创建表
db.create_table(sql_create_users_table)
db.close()

current_script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
app = FastAPI()
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 设置允许的origins来源
    allow_credentials=True,
    allow_methods=["*"],  # 设置允许跨域的http方法，比如 get、post、put等。
    allow_headers=["*"])  # 允许跨域的headers，可以用来鉴别来源等作用。


@app.post("/upload")
async def handle(background_task: BackgroundTasks, file: UploadFile = File(...), user_name: Optional[str] = Form(...)):
    try:
        doc_id = hashlib.md5((file.filename + user_name).encode('utf-8')).hexdigest()
        # 文件保存路径
        file_path = os.path.join(current_script_dir, f"{doc_id}")
        if not os.path.exists(file_path):
            os.makedirs(file_path)
        md_file_path = file_path
        file_path = os.path.join(file_path, f"{file.filename}")  # 假设保存为文本文件
        # 保存文件
        # 重置文件指针到开头，以便可以读取文件并保存
        await file.seek(0)

        # 保存文件

        with open(file_path, "wb") as f:
            while chunk := await file.read(1024):  # 读取文件块
                f.write(chunk)
        dbM = SQLiteORM(db_file)
        dbM.create("file_task",
                  {"task_id": doc_id, "file_path": file_path, "md_file_path": md_file_path, "status": "waiting"})
        dbM.close()
        return {"message": "success", 'task_id': doc_id, 'filename': file.filename}
    except Exception as e:
        print(e)
        return {"message": str(e), 'task_id': None, 'filename': file.filename}

@app.get("/download/{task_id}")
async def download_file(task_id: str):
    # 查询数据库以获取文件路径
    db = SQLiteORM(db_file)
    result = db.read("file_task", {"task_id": task_id})
    db.close()

    if not result:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Task ID not found")


    status = result[0][3]
    if status == "success":
        file_path = result[0][1]  # 假设 file_path 是查询结果的第三个元素
        file_name, file_extension = os.path.splitext(file_path)  # 分离文件名和扩展名
        md_file_path = f"{file_name}.md"  # 构造新的文件路径
        # 读取文件并转换为 base64
        with open(md_file_path, "rb") as file:
            file_data = file.read()
            base64_data = base64.b64encode(file_data).decode('utf-8')  # 转换为 base64 并解码为字符串

        # 返回 base64 编码的文件数据
        return {"message": "success", 'task_id': task_id, 'filename': result[0][1], "data": base64_data}

    elif status == "processing":
        return {"message": "processing", 'task_id': task_id, 'filename': result[0][1]}

    elif status == "waiting":
        return {"message": "waiting", 'task_id': task_id, 'filename': result[0][1]}

    else:
        return {"message": "error", 'task_id': task_id, 'filename': result[0][1]}


class AddLink(BaseModel):
    link: str



# 定义一个队列
q = queue.Queue(maxsize=20)  # 可选参数 maxsize 设置队列的最大长度


def producer():
    dbP = SQLiteORM(db_file)
    while True:
        waitingList = dbP.read("file_task", {"status": "waiting"})
        for waiting in waitingList:
            q.put(waiting)
            dbP.update("file_task", {"status": "processing"}, {"task_id": waiting[0]})
        time.sleep(5)  # 模拟生产数据的时间


def consumer():
    dbC = SQLiteORM(db_file)
    while True:
        item = q.get()  # 当队列为空时，get() 方法会阻塞直到有数据可用
        print('Consumer 消费了', item)
        try:
            # 处理PDF转换任务
            Pdf2MD.processPdf2MD(item)
            dbC.update("file_task", {"status": "success"}, {"task_id": item[0]})
        except Exception as e:
            # 处理异常
            dbC.update("file_task", {"status": "error"}, {"task_id": item[0]})
            print(f"An error occurred while processing PDF to MD: {e}")

        q.task_done()  # 通知队列此任务已完成
        time.sleep(1)  # 模拟消费数据的时间


@app.on_event("startup")
async def startup_event():
    # 创建生产者线程
    producer_thread = threading.Thread(target=producer, daemon=True)
    producer_thread.start()

    # 创建消费者线程
    consumer_thread = threading.Thread(target=consumer, daemon=True)
    consumer_thread.start()


if __name__ == '__main__':
    uvicorn.run('main:app', host="0.0.0.0", reload=True)
