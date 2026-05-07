"""Detect ATS provider and token from a job URL."""
from urllib.parse import urlparse


def detect_ats(url: str) -> tuple[str | None, str | None]:
    """
    Return (ats_provider, ats_token) for a given job URL.

    ats_provider is one of: greenhouse, lever, ashby, workday, icims,
    smartrecruiters, taleo, brassring, jobvite, recruitee, workable,
    or None if unknown.

    ats_token is the company identifier within that ATS, when extractable.
    """
    if not url:
        return (None, None)

    try:
        parsed = urlparse(url)
    except Exception:
        return (None, None)

    host = (parsed.hostname or "").lower()
    path_parts = [p for p in parsed.path.split("/") if p]

    # Greenhouse: boards.greenhouse.io/{token}/jobs/{id}
    #             job-boards.greenhouse.io/{token}/jobs/{id}
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        token = path_parts[0] if path_parts else None
        return ("greenhouse", token)

    # Lever: jobs.lever.co/{token}/{id}
    if host == "jobs.lever.co":
        token = path_parts[0] if path_parts else None
        return ("lever", token)

    # Ashby: jobs.ashbyhq.com/{token}/{id}
    if host == "jobs.ashbyhq.com":
        token = path_parts[0] if path_parts else None
        return ("ashby", token)

    # Workday: {company}.wdN.myworkdayjobs.com/...
    if host.endswith(".myworkdayjobs.com"):
        token = host.split(".")[0]
        return ("workday", token)

    # iCIMS: careers-{company}.icims.com or {company}.icims.com
    if host.endswith(".icims.com"):
        sub = host.split(".")[0]
        token = sub.replace("careers-", "")
        return ("icims", token)

    # SmartRecruiters: jobs.smartrecruiters.com/{token}
    if host == "jobs.smartrecruiters.com" or host.endswith(".smartrecruiters.com"):
        token = path_parts[0] if path_parts else None
        return ("smartrecruiters", token)

    # Taleo: {company}.taleo.net/...
    if host.endswith(".taleo.net"):
        token = host.split(".")[0]
        return ("taleo", token)

    # Kenexa BrassRing: sjobs.brassring.com (no clean token)
    if host == "sjobs.brassring.com":
        return ("brassring", None)

    # Jobvite: jobs.jobvite.com/{token}/job/...
    if host == "jobs.jobvite.com":
        token = path_parts[0] if path_parts else None
        return ("jobvite", token)

    # Recruitee: {company}.recruitee.com
    if host.endswith(".recruitee.com"):
        token = host.split(".")[0]
        return ("recruitee", token)

    # Workable: apply.workable.com/{token}
    if host == "apply.workable.com":
        token = path_parts[0] if path_parts else None
        return ("workable", token)

    return (None, None)


if __name__ == "__main__":
    # Smoke test with real URLs from the listings we inspected.
    tests = [
        "https://www.tesla.com/careers/search/job/241053",
        "https://autodesk.wd1.myworkdayjobs.com/uni/job/Montreal-QC-CAN/Stagiaire_25WD91266-1",
        "https://thermofisher.wd5.myworkdayjobs.com/ThermoFisherCareers/job/Waltham/IT-Services_R-01328653",
        "https://boards.greenhouse.io/stripe/jobs/12345",
        "https://job-boards.greenhouse.io/minitab/jobs/7588696003",
        "https://jobs.lever.co/figma/abc-123",
        "https://jobs.ashbyhq.com/simple-ai/63d1ef98",
        "https://www.amazon.jobs/en/jobs/2993367/asic-engineering-internship",
    ]
    for url in tests:
        print(f"{detect_ats(url)!s:<35}  {url}")