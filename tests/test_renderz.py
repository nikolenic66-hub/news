import unittest

from app.renderz import (
    _detail_fields,
    _extract_search_query,
    _format_card,
    _player_links,
    _transliterate_name_token,
    is_player_data_question,
    is_verified_player_context,
    secondary_player_search,
)


class RenderZParsingTests(unittest.TestCase):
    def test_player_list_extracts_ovr_and_group_stats(self):
        html = """
        <a href="/player/30924202-essien">
          124 CDM Essien Essien CM 147 PAC 131 SHO 136 PAS
          144 DRI 153 DEF 151 PHY
        </a>
        <a href="/player/30924202-essien">124 CDM Essien 13.3B</a>
        """
        cards = _player_links(html, "Essien")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["ovr"], 124)
        self.assertEqual(cards[0]["position"], "CDM")
        self.assertEqual(cards[0]["PAC"], 147)
        self.assertEqual(cards[0]["PHY"], 151)
        self.assertEqual(cards[0]["market_price"], "13.3B")
        self.assertEqual(cards[0]["url"], "https://renderz.app/player/30924202-essien")

    def test_search_rejects_unmatched_page_rows(self):
        html = '<a href="/player/30924202-essien">124 CDM Essien 147 PAC</a>'
        self.assertEqual(_player_links(html, "Messi"), [])

    def test_search_requires_complete_name_tokens(self):
        html = """
        <a href="/player/1-haaland">115 ST Erling Haaland 160 PAC</a>
        <a href="/player/2-ham">115 ST Ham 150 PAC</a>
        """
        self.assertEqual([card["url"] for card in _player_links(html, "Haaland")],
                         ["https://renderz.app/player/1-haaland"])
        self.assertEqual(_player_links(html, "land"), [])

    def test_search_supports_multiword_and_accented_names(self):
        html = """
        <a href="/player/1-van-dijk">120 CB Virgil van Dijk 130 DEF</a>
        <a href="/player/2-ribery">118 LW Franck Ribéry 160 PAC</a>
        """
        self.assertEqual(len(_player_links(html, "van Dijk")), 1)
        self.assertEqual(len(_player_links(html, "Ribery")), 1)

    def test_ovr_without_player_name_does_not_return_random_cards(self):
        html = '<a href="/player/1-haaland">115 ST Haaland 160 PAC</a>'
        self.assertEqual(_player_links(html, "115"), [])

    def test_russian_name_fallback_transliterates(self):
        self.assertEqual(_transliterate_name_token("Фоден"), "foden")
        self.assertEqual(_transliterate_name_token("Мусиала"), "musiala")
        self.assertEqual(_transliterate_name_token("Haaland"), "Haaland")

    def test_search_filters_exact_requested_ovr(self):
        html = """
        <a href="/player/1-haaland">115 ST Haaland 160 PAC 155 SHO</a>
        <a href="/player/2-haaland">118 ST Haaland 163 PAC 159 SHO</a>
        """
        cards = _player_links(html, "Haaland 115")
        self.assertEqual([card["ovr"] for card in cards], [115])

    def test_detail_page_reads_visible_player_fields(self):
        html = """
        <h1>Michaël Essien — 124 OVR · FC Mobile</h1>
        <div>NATION/REGION Ghana</div>
        <div>Height 5'10" (177 cm) Weight 80 kg</div>
        <div>Work Rate (ATT) / Work Rate (DEF) Medium/High</div>
        <div>Like Dislike Stellar Icons Player</div>
        <div>Skill Moves (3) ★★★</div>
        <div>STRONG FOOT / WEAK FOOT RIGHT / (4) ★★★★</div>
        <div>Relentless Level 1 Anticipate Level 2</div>
        <div>Added on 11/18/2026</div>
        """
        data = _detail_fields(html)
        self.assertEqual(data["name"], "Michaël Essien")
        self.assertEqual(data["ovr"], 124)
        self.assertEqual(data["nation"], "Ghana")
        self.assertEqual(data["weight"], "80 kg")
        self.assertEqual(data["work_rate"], "Medium/High")
        self.assertIn("Relentless", data["playstyles"])
        self.assertEqual(data["program"], "Stellar Icons")
        self.assertEqual(data["skill_moves"], "3")
        self.assertEqual(data["strong_foot"], "RIGHT / weak 4")

    def test_query_extraction_and_question_detection(self):
        self.assertEqual(_extract_search_query("Какой OVR у Месси?"), "Месси")
        self.assertEqual(_extract_search_query("Сравни Месси и Роналду"), "Месси и Роналду")
        self.assertEqual(_extract_search_query("Compare Messi vs Ronaldo"), "Messi vs Ronaldo")
        self.assertTrue(is_player_data_question("Сколько OVR у Haaland?"))
        self.assertTrue(is_player_data_question("Messi 115"))
        self.assertTrue(is_player_data_question("Salah stats"))
        self.assertTrue(is_player_data_question("Essien 124"))
        self.assertTrue(is_player_data_question("Foden stats"))
        self.assertTrue(is_player_data_question("Kvaratskhelia player card"))
        self.assertFalse(is_player_data_question("Кто выиграл матч вчера?"))

    def test_player_context_verification_requires_parsed_card_marker(self):
        self.assertTrue(is_verified_player_context(
            "ПРОВЕРЕННЫЕ ДАННЫЕ КАРТОЧЕК RENDERZ (время получения — 2026-11-24 UTC)"
        ))
        self.assertFalse(is_verified_player_context(
            "ДАННЫЕ RENDERZ: по запросу «Messi» карточка не найдена"
        ))
        self.assertFalse(is_verified_player_context(""))
        self.assertFalse(is_verified_player_context(
            "RenderZ вернул ошибку, вот примерная карточка"
        ))

    def test_format_does_not_invent_missing_fields(self):
        card = {"label": "124 CDM Essien", "ovr": 124, "position": "CDM",
                "url": "https://renderz.app/player/30924202-essien"}
        result = _format_card(card)
        self.assertIn("124 OVR", result)
        self.assertNotIn("PAC", result)
        self.assertNotIn("цена", result.casefold())

    async def test_secondary_search_returns_publication_links_without_verified_stats(self):
        import asyncio
        from unittest.mock import AsyncMock
        import xml.etree.ElementTree as ET

        response = AsyncMock()
        response.text = """<rss><channel><item><title>FC Mobile player card update</title><link>https://example.com/card-news</link><description>Discussion of cards</description><pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
        response.raise_for_status = lambda: None
        client = AsyncMock()
        client.get = AsyncMock(return_value=response)

        result = await secondary_player_search("OVR Messi card", client)
        self.assertIn("Bing News RSS", result)
        self.assertIn("https://example.com/card-news", result)
        self.assertIn("не подтверждённая карточка", result)
        self.assertFalse(is_verified_player_context(result)



if __name__ == "__main__":
    unittest.main()
