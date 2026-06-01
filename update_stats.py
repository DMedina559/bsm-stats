import requests, json, os

def get_stats():
    # 1. PyPI Installs
    try:
        res = requests.get("https://img.shields.io/pypi/dt/bedrock-server-manager.json").json()
        val_str = res.get("value", "0").replace(" ", "")
        if val_str.endswith("k"):
            pypi = int(float(val_str[:-1]) * 1000)
        elif val_str.endswith("M"):
            pypi = int(float(val_str[:-1]) * 1000000)
        else:
            pypi = int(val_str)
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
    ghcr = 0
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        query = """
        query {
          user(login: "DMedina559") {
            packages(first: 1, names: ["bedrock-server-manager"], packageType: CONTAINER) {
              nodes {
                statistics {
                  downloadsTotalCount
                }
              }
            }
          }
        }
        """
        try:
            res = requests.post(
                "https://api.github.com/graphql", 
                json={'query': query}, 
                headers={"Authorization": f"Bearer {token}"}
            ).json()
            ghcr = res['data']['user']['packages']['nodes'][0]['statistics']['downloadsTotalCount']
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
            "label": "Total Installs",
            "message": format_num(get_stats()),
            "color": "green"
        }, f)
