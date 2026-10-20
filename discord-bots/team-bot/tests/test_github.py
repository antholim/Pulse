from types import SimpleNamespace

from githubkit import AppInstallationAuthStrategy, TokenAuthStrategy

from team_bot.config import GitHubAuth
from team_bot.services import github as gh

from conftest import utc

MILESTONE_JSON = {
    "number": 2,
    "title": "Iteration 2",
    "state": "open",
    "due_on": "2026-10-20T00:00:00Z",
    "html_url": "https://github.com/antholim/Pulse/milestone/2",
}

PR_JSON = {
    "number": 43,
    "title": "Add GitHub ticket generator with story points",
    "user": {"login": "AbdelrahmanWM"},
    "html_url": "https://github.com/antholim/Pulse/pull/43",
    "draft": False,
    "created_at": "2026-10-03T15:00:00Z",
    "requested_reviewers": [{"login": "antholim"}],
    "requested_teams": [{"name": "backend"}],
}


def test_milestone_from_json():
    milestone = gh.milestone_from_json(MILESTONE_JSON)
    assert milestone.number == 2
    assert milestone.due_on == utc("2026-10-20T00:00:00")
    assert gh.milestone_from_json(MILESTONE_JSON | {"due_on": None}).due_on is None


def test_pull_request_from_json():
    pr = gh.pull_request_from_json(PR_JSON)
    assert pr.author == "AbdelrahmanWM"
    assert pr.requested_reviewers == ("antholim", "backend")
    assert pr.created_at == utc("2026-10-03T15:00:00")
    minimal = gh.pull_request_from_json(
        {k: v for k, v in PR_JSON.items() if k not in ("requested_reviewers", "requested_teams")}
        | {"user": None}
    )
    assert minimal.author == "unknown"
    assert minimal.requested_reviewers == ()


def test_build_client_picks_auth_strategy():
    token_client = gh.build_client(GitHubAuth(token="t"))
    assert isinstance(token_client.auth, TokenAuthStrategy)
    app_client = gh.build_client(GitHubAuth(app_id="1", installation_id=2, private_key="k"))
    assert isinstance(app_client.auth, AppInstallationAuthStrategy)


class FakeRest:
    def __init__(self):
        self.calls = []
        self.issues = SimpleNamespace(async_list_milestones=self._milestones)
        self.pulls = SimpleNamespace(async_list=self._pulls)

    async def _milestones(self, owner, repo, **kwargs):
        self.calls.append(("milestones", owner, repo, kwargs))
        return SimpleNamespace(json=lambda: [MILESTONE_JSON])

    async def _pulls(self, owner, repo, **kwargs):
        self.calls.append(("pulls", owner, repo, kwargs))
        return SimpleNamespace(json=lambda: [PR_JSON, PR_JSON | {"number": 50, "draft": True}])


async def test_service_caches_milestones(monkeypatch):
    rest = FakeRest()
    service = gh.GitHubService(SimpleNamespace(rest=rest), "antholim", "Pulse")
    clock = [1000.0]
    monkeypatch.setattr(gh.time, "monotonic", lambda: clock[0])

    first = await service.milestones()
    await service.milestones()
    assert len(rest.calls) == 1
    assert rest.calls[0] == ("milestones", "antholim", "Pulse", {"state": "all", "per_page": 100})
    assert first[0].title == "Iteration 2"

    clock[0] += gh.MILESTONE_CACHE_SECONDS + 1
    await service.milestones()
    assert len(rest.calls) == 2


async def test_service_lists_open_pull_requests():
    rest = FakeRest()
    service = gh.GitHubService(SimpleNamespace(rest=rest), "antholim", "Pulse")
    prs = await service.open_pull_requests()
    assert [pr.number for pr in prs] == [43, 50]
    assert rest.calls[0][3]["state"] == "open"  # the JS bot sent the invalid "opened"


class FakeRoutingClient:
    """githubkit stand-in for the review routing calls: records calls, serves pages."""

    def __init__(self, graphql=None):
        self.calls = []
        self._graphql = graphql or {}
        self.rest = SimpleNamespace(
            pulls=SimpleNamespace(
                async_request_reviewers=self._record("request", lambda: {}),
            ),
        )

    def _record(self, name, body):
        async def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            data = body()
            return SimpleNamespace(json=lambda: data)

        return call

    async def async_graphql(self, query, variables):
        self.calls.append(("graphql", variables))
        return self._graphql


def routing_service(client):
    return gh.GitHubService(client, "antholim", "Pulse")


def test_pull_request_labels_and_updated_at():
    pr = gh.pull_request_from_json(
        PR_JSON | {"labels": [{"name": "data"}], "updated_at": "2026-10-19T10:00:00Z"}
    )
    assert pr.labels == ("data",)
    assert pr.updated_at == utc("2026-10-19T10:00:00")
    assert gh.pull_request_from_json(PR_JSON).labels == ()


async def test_service_review_context():
    graphql = {
        "repository": {
            "pullRequest": {
                "closingIssuesReferences": {
                    "nodes": [
                        {"labels": {"nodes": [{"name": "data"}, {"name": "Release 1"}]}},
                        {"labels": {"nodes": [{"name": "infra"}]}},
                    ]
                },
                "timelineItems": {"nodes": [{"createdAt": "2026-10-19T22:59:59Z"}]},
            }
        }
    }
    client = FakeRoutingClient(graphql=graphql)
    context = await routing_service(client).review_context(12)
    assert context.issue_labels == ("data", "Release 1", "infra")
    assert context.reopened_at == utc("2026-10-19T22:59:59")
    assert client.calls[0] == ("graphql", {"owner": "antholim", "repo": "Pulse", "number": 12})
    empty = FakeRoutingClient(graphql={"repository": {"pullRequest": None}})
    assert await routing_service(empty).review_context(12) == gh.ReviewContext((), None)


async def test_service_request_reviewers():
    client = FakeRoutingClient()
    await routing_service(client).request_reviewers(12, ["bob"])
    assert client.calls == [("request", ("antholim", "Pulse", 12), {"reviewers": ["bob"]})]
