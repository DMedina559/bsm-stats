import requests, json, os

def get_stats():
    # 1. PyPI Installs
    try:
        res = requests.get("https://pepy.tech/api/v2/projects/bedrock-server-manager").json()
        pypi = res.get("total_downloads", 0)
    except Exception as e:
        print(f"Failed to fetch PyPI stats: {e}")
        pypi = 0
    
    # 2. Docker Hub Pulls
    try:
        docker = requests.get("https://hub.docker.com/v2/repositories/dmedina559/bedrock-server-manager/").json().get("pull_count", 0)
    except Exception as e:
        print(f"Failed to fetch Docker stats: {e}")
        docker = 0

    # 3. GitHub Container Registry (GHCR) Pulls
    try:
        url = "https://github.com/DMedina559/bedrock-server-manager/pkgs/container/bedrock-server-manager"
        html = requests.get(url).text
        # Scrape the Total downloads count from the HTML
        import re
        match = re.search(r'Total downloads</span>\s*<h3[^>]*title="([0-9,]+)"', html)
        if match:
            ghcr = int(match.group(1).replace(',', ''))
        else:
            print("Failed to find GHCR downloads in HTML.")
            ghcr = 0
    except Exception as e:
        print(f"Failed to fetch GHCR stats: {e}")
        ghcr = 0

    total = pypi + docker + ghcr
    print(f"PyPI: {pypi} | Docker Hub: {docker} | GHCR: {ghcr} | TOTAL: {total}")
    return total

def format_num(num):
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    if num >= 1000:
        return f"{num/1000:.1f}k"
    return str(num)

if __name__ == "__main__":
    # Format required by Shields.io endpoint
    with open("downloads.json", "w") as f:
        json.dump({
            "schemaVersion": 1,
            "label": "Downloads",
            "message": format_num(get_stats()),
            "color": "orange"
        }, f)
