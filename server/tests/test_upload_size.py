import io
import json

def test_upload_exact_memory_size(client):
    content = b"\x00" * 614400
    resp = client.post(
        "/api/upload",
        params={"task_id": 99},
        files={"file": ("capture.bin", io.BytesIO(content), "application/octet-stream")},
    )
    if resp.status_code != 200:
        print("Response Text:", resp.text)
    assert resp.status_code == 200
