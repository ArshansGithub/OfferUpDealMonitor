# db.py
import pymongo
from loguru import logger
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["offerup_bot"]
tasks_collection = db["tasks"]

def create_task(task_doc: dict):
    result = tasks_collection.insert_one(task_doc)
    logger.info(f"Inserted task: {task_doc.get('task_id')} with id: {result.inserted_id}")
    return result

def update_task(task_id: str, update_doc: dict):
    result = tasks_collection.update_one({"task_id": task_id}, {"$set": update_doc})
    logger.info(f"Updated task {task_id} with {update_doc}")
    return result

def get_tasks_by_user(user_id: int):
    tasks = list(tasks_collection.find({"user_id": user_id}))
    logger.info(f"Fetched {len(tasks)} tasks for user {user_id}")
    return tasks

def get_task(task_id: str):
    task = tasks_collection.find_one({"task_id": task_id})
    logger.info(f"Fetched task: {task_id}")
    return task

def delete_task(task_id: str):
    result = tasks_collection.delete_one({"task_id": task_id})
    logger.info(f"Deleted task: {task_id}")
    return result
