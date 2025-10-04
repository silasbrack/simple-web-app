from locust import HttpUser, task

class QuickstartUser(HttpUser):
    @task
    def home_page(self):
        self.client.get("/")

