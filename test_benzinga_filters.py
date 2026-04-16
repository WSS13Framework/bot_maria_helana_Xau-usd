import unittest

from benzinga_news import filter_relevant_news, find_matching_keywords, parse_benzinga_xml


class BenzingaKeywordFilterTests(unittest.TestCase):
    def test_matches_prefix_keywords_for_geopolitical_headlines(self) -> None:
        item = {
            "title": "Gold rallies after geopolitical tensions rise",
            "teaser": "",
            "body": "",
            "channels": [],
            "tags": [],
            "stocks": [],
        }

        matches = find_matching_keywords(item, ["gold", "geopolit", "war"])

        self.assertEqual(matches, ["gold", "geopolit"])

    def test_filters_using_body_html_and_metadata(self) -> None:
        items = [
            {
                "title": "Market wrap",
                "teaser": "",
                "body": "<p>Fed officials warn that inflation is still sticky.</p>",
                "channels": ["Economics"],
                "tags": ["Macro"],
                "stocks": [],
            },
            {
                "title": "Tesla opens higher",
                "teaser": "",
                "body": "<p>No macro driver here.</p>",
                "channels": ["Equities"],
                "tags": ["Momentum"],
                "stocks": ["TSLA"],
            },
        ]

        filtered = filter_relevant_news(items, ["fed", "inflation", "gold"])

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["matched_keywords"], ["fed", "inflation"])

    def test_parses_basic_xml_payload(self) -> None:
        xml_payload = """
        <response>
          <item>
            <id>1</id>
            <title>Gold gains after Fed comments</title>
            <teaser>Short summary</teaser>
            <body>&lt;p&gt;Inflation cools slightly.&lt;/p&gt;</body>
            <url>https://example.com/news/1</url>
            <created>Thu, 16 Apr 2026 09:00:00 -0400</created>
            <channels>
              <channel><name>Economics</name></channel>
            </channels>
            <tags>
              <tag><name>Gold</name></tag>
            </tags>
          </item>
        </response>
        """

        parsed = parse_benzinga_xml(xml_payload)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Gold gains after Fed comments")
        self.assertEqual(parsed[0]["channels"], ["Economics"])
        self.assertEqual(parsed[0]["tags"], ["Gold"])


if __name__ == "__main__":
    unittest.main()
