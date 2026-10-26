import httpx

from applybot.sources import ashby, boards, greenhouse, lever, simplify


def client(routes: dict):
    def handler(req: httpx.Request):
        for frag, payload in routes.items():
            if frag in str(req.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_simplify():
    data = [
        {"id": "a", "company_name": "Waymo", "title": "SWE Intern", "active": True, "is_visible": True,
         "url": "https://x/apply", "locations": ["Mountain View, CA"], "date_posted": 1791324476,
         "terms": ["Summer 2027"], "sponsorship": "Other"},
        {"id": "b", "company_name": "Old", "title": "Intern", "active": False, "url": "https://y"},
    ]
    jobs = simplify.fetch({"repos": ["SimplifyJobs/Summer2027-Internships"]}, {}, client({"listings.json": data}))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Waymo" and j.job_type == "internship" and j.posted_at.startswith("2026")
    assert j.extra["sponsorship"] == "Other"


def test_greenhouse():
    payload = {"jobs": [{"id": 42, "title": "Software Engineer, New Grad", "absolute_url": "https://s.com/j/42",
                         "location": {"name": "Remote - US"}, "content": "&lt;p&gt;Use &lt;b&gt;Go&lt;/b&gt;&lt;/p&gt;",
                         "updated_at": "2026-10-01T00:00:00Z", "company_name": "Stripe"}]}
    j = greenhouse.fetch({"companies": ["stripe", "missing"]}, {}, client({"boards/stripe/": payload}))[0]
    assert j.apply_url == "https://job-boards.greenhouse.io/stripe/jobs/42"
    assert j.remote and "Use" in j.description and "<b>" not in j.description


def test_lever():
    payload = [{"id": "x1", "text": "Backend Intern", "hostedUrl": "https://jobs.lever.co/p/x1",
                "applyUrl": "https://jobs.lever.co/p/x1/apply", "categories": {"location": "NYC", "commitment": "Intern"},
                "descriptionPlain": "Build things", "lists": [{"text": "Reqs", "content": "<li>Python</li>"}],
                "createdAt": 1790000000000}]
    j = lever.fetch({"companies": ["p"]}, {}, client({"postings/p": payload}))[0]
    assert j.apply_url.endswith("/apply") and j.job_type == "internship" and "Python" in j.description


def test_ashby():
    payload = {"jobs": [{"id": "z", "title": " Software Engineer ", "location": "SF", "isRemote": False,
                         "jobUrl": "https://jobs.ashbyhq.com/r/z", "applyUrl": "https://jobs.ashbyhq.com/r/z/application",
                         "descriptionPlain": "desc", "publishedAt": "2026-10-01", "employmentType": "FullTime"}]}
    j = ashby.fetch({"companies": ["r"]}, {}, client({"job-board/r": payload}))[0]
    assert j.title == "Software Engineer" and j.apply_url.endswith("/application")


def test_remotive_and_remoteok():
    rem = {"jobs": [{"id": 1, "url": "https://r/1", "title": "Python Developer", "company_name": "A",
                     "job_type": "full_time", "publication_date": "2026-10-01", "description": "<p>hi</p>"}]}
    jobs = boards.fetch_remotive({}, {"keywords": ["python", "django"]}, client({"remotive.com": rem}))
    assert len(jobs) == 1 and jobs[0].remote
    rok = [{"legal": "notice"}, {"id": 9, "position": "Dev Intern", "company": "B", "url": "https://ro/9",
                                 "description": "x", "date": "2026-10-01", "tags": ["dev"]}]
    jobs = boards.fetch_remoteok({}, {}, client({"remoteok.com": rok}))
    assert len(jobs) == 1 and jobs[0].job_type == "internship"
