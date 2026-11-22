# Run map tracker
app to track orienteering runners

live tracking of gps location, upload of gpx, visualisation of progress


## How it looks:
<img width="1919" height="899" alt="Snímek obrazovky z 2026-11-21 13-09-18" src="https://github.com/user-attachments/assets/348fe90e-ee07-4702-bbee-9c284836523c" />




## How to run
pip install -r requirements.txt

create Mapy.com account, let at least one person share position with you and copy this Cookie token - you may get one in developer view of website
<img width="920" height="756" alt="image" src="https://github.com/user-attachments/assets/d91513d0-5525-471e-aaab-dfc1772a759d" />
to add sharing of more people, just open the invite link with the same account (easiest way is to open it in the same browser)




create .env file with copy there the cookie token into: COOKIE_TOKEN 


run the app with:
```
uvicorn main:app --host 0.0.0.0 --port 8000
```

it runs locally, computer is server (it must be running to get live data)

you can upload ".gpx" file. Timestamps from this file will be automatically recognized, in case the exported gpx doesn't have timestamps, you can add starting and finishing time to add uniform distribution on the track.


