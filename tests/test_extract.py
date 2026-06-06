import unittest

from ogrescanbot.extract import extract_token_queries


OGRE_CA = "5RAZMWd9RiKfodLPQ73cFk4CMoJzTUSATUoRdDThpump"


class ExtractTokenQueriesTest(unittest.TestCase):
    def test_normal_words_do_not_trigger_auto_scan(self):
        self.assertEqual(extract_token_queries("can someone check this", include_tickers=False), [])

    def test_dollar_ticker_is_ignored_when_auto_tickers_disabled(self):
        self.assertEqual(extract_token_queries("$CAN looks active", include_tickers=False), [])

    def test_dollar_ticker_still_works_for_explicit_commands(self):
        self.assertEqual(extract_token_queries("/scan $OGRE", include_tickers=True), ["OGRE"])

    def test_valid_solana_ca_still_triggers_auto_scan(self):
        self.assertEqual(extract_token_queries(f"ca {OGRE_CA}", include_tickers=False), [OGRE_CA])

    def test_pump_link_still_triggers_auto_scan(self):
        self.assertEqual(extract_token_queries(f"https://pump.fun/coin/{OGRE_CA}", include_tickers=False), [OGRE_CA])


if __name__ == "__main__":
    unittest.main()
