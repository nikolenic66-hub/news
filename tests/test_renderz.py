import unittest

from app.renderz import (
    _detail_fields,
    _extract_search_query,
    _format_card,
    _player_links,
    is_player_data_question,
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
        self.assertEqual(cards[0]["url"], "https://renderz.app/player/30924202-essien")

    def test_search_rejects_unmatched_page_rows(self):
        html = '<a href="/player/30924202-essien">124 CDM Essien 147 PAC</a>'
        self.assertEqual(_player_links(html, "Messi"), [])

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

    def test_query_extraction_and_question_detection(self):
        self.assertEqual(_extract_search_query("Какой OVR у Месси?"), "Месси")
        self.assertTrue(is_player_data_question("Сколько OVR у Haaland?"))
        self.assertFalse(is_player_data_question("Кто выиграл матч вчера?"))

    def test_format_does_not_invent_missing_fields(self):
        card = {"label": "124 CDM Essien", "ovr": 124, "position": "CDM",
                "url": "https://renderz.app/player/30924202-essien"}
        result = _format_card(card)
        self.assertIn("124 OVR", result)
        self.assertNotIn("PAC", result)
        self.assertNotIn("цена", result.casefold())


if __name__ == "__main__":
    unittest.main()
