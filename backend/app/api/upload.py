"""File upload endpoints — for video clips and other media."""

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services.storage import upload_file, get_public_url, list_user_videos

router = APIRouter()

ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm",
    "video/x-msvideo", "video/x-matroska",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


@router.post("/upload/video")
async def upload_video(file: UploadFile = File(...)):
    """Upload a video clip for later use in video assembly."""
    if file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: {ALLOWED_VIDEO_TYPES}",
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 100 MB.")

    key = upload_file(data, file.filename or "video.mp4", file.content_type)
    url = get_public_url(key)

    return {"key": key, "url": url, "size": len(data), "filename": file.filename}


@router.get("/videos")
async def get_videos():
    """List all uploaded video clips."""
    return list_user_videos()


@router.post("/upload/videos")
async def upload_multiple_videos(files: list[UploadFile] = File(...)):
    """Upload multiple video clips at once."""
    results = []
    for file in files:
        if file.content_type not in ALLOWED_VIDEO_TYPES:
            results.append({"filename": file.filename, "error": "Invalid file type"})
            continue

        data = await file.read()
        if len(data) > MAX_FILE_SIZE:
            results.append({"filename": file.filename, "error": "File too large"})
            continue

        key = upload_file(data, file.filename or "video.mp4", file.content_type)
        results.append({
            "filename": file.filename,
            "key": key,
            "url": get_public_url(key),
            "size": len(data),
        })

    return results
