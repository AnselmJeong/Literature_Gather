
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from citation_snowball.services.semantic_scholar import SemanticScholarClient
from citation_snowball.core.models import Work, WorksResponse

@pytest.fixture
def api_client():
    client = SemanticScholarClient(api_key="test_key", db=None)
    # Mock settings to avoid reading .env
    client.settings = MagicMock()
    client.settings.semantic_scholar_api_key = "test_key"
    
    # Mock the internal http client to avoid actual requests
    client._client = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_get_paper(api_client):
    # Mock _fetch to return dictionary
    with patch.object(api_client, '_fetch', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "paperId": "123",
            "title": "Test Paper",
            "year": 2023,
            "authors": [{"authorId": "a1", "name": "Author 1"}]
        }
        
        work = await api_client.get_paper("123")
        
        assert isinstance(work, Work)
        assert work.paperId == "123"
        assert work.title == "Test Paper"
        assert work.year == 2023
        assert len(work.authors) == 1
        assert work.authors[0].name == "Author 1"

@pytest.mark.asyncio
async def test_get_paper_citations(api_client):
    with patch.object(api_client, '_fetch', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "offset": 0,
            "next": 100,
            "data": [
                {
                    "citingPaper": {
                        "paperId": "456",
                        "title": "Citing Paper",
                        "year": 2024
                    }
                }
            ]
        }
        
        response = await api_client.get_paper_citations("123")
        
        assert isinstance(response, WorksResponse)
        assert len(response.results) == 1
        assert isinstance(response.results[0], Work)
        assert response.results[0].paperId == "456"
        assert response.results[0].title == "Citing Paper"

@pytest.mark.asyncio
async def test_get_paper_references(api_client):
    with patch.object(api_client, '_fetch', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {
            "offset": 0,
            "next": None,
            "data": [
                {
                    "citedPaper": {
                        "paperId": "789",
                        "title": "Cited Paper",
                        "year": 2020
                    }
                }
            ]
        }
        
        response = await api_client.get_paper_references("123")
        
        assert isinstance(response, WorksResponse)
        assert len(response.results) == 1
        assert response.results[0].paperId == "789"
