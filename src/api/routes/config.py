from fastapi import APIRouter

router = APIRouter()

@router.get("/config/")
async def get_config():
    # Replace with actual configuration loading logic
    config = {"setting1": "value1", "setting2": "value2"}
    return config

@router.put("/config/")
async def update_config(new_config: dict):
    # Replace with actual configuration updating logic
    print(f"Received new configuration: {new_config}")
    return {"message": "Configuration updated successfully"}

@router.get("/config/{setting_name}")
async def get_specific_setting(setting_name: str):
    # Replace with actual logic to retrieve a specific setting
    config = {"setting1": "value1", "setting2": "value2"}
    if setting_name in config:
        return {setting_name: config[setting_name]}
    return {"message": f"Setting '{setting_name}' not found"}