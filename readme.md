# Run map tracker
app to track orienteering runners

live tracking of gps location



## run commands
pip install -r requirements.txt
create .env file with COOKIE_TOKEN - token from mapy.com website



uvicorn main:app --host 0.0.0.0 --port 8000
