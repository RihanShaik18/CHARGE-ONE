from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return{
        "Message":"Bus tracking system backend is running"
    }