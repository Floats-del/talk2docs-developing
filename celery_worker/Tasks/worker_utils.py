from utils.schemas import APIResponse
def worker_result_handler(result: APIResponse):
    if result.success:
        return result.data
    
    reason: dict = {
        "status": result.data["status"],
        "error_code": result.error_code,
        "error_message": result.error_message,
        "failed": result.data["failed"],
        "task_id": result.data["task_id"],
        "state": result.data["state"]
    }
    return reason