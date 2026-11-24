import unittest
from app.logic import is_fc_topic,is_direct_message,should_spontaneously_reply,is_bot_name_call,is_recent_bot_followup
class LogicTests(unittest.TestCase):
 def test_fc_topic_detected(self):
  self.assertTrue(is_fc_topic("Какой OVR у этой карточки?"))
  self.assertTrue(is_fc_topic("Собрал новый состав"))
 def test_offtopic_ignored(self):
  self.assertFalse(is_fc_topic("Кто смотрел кино вчера?"))
 def test_direct_mentions(self):
  self.assertTrue(is_direct_message("привет @FCMate_bot","FCMate_bot",False))
  self.assertTrue(is_direct_message("ответ","FCMate_bot",True))
  self.assertFalse(is_direct_message("просто чат","FCMate_bot",False))
 def test_vasek_name_calls(self):
  self.assertTrue(is_bot_name_call("Васёк, глянь состав"))
  self.assertTrue(is_bot_name_call("эй, Вась, как тебе карта?"))
  self.assertTrue(is_bot_name_call("Васек ты тут?"))
  self.assertFalse(is_bot_name_call("у Васи новый состав"))
  self.assertFalse(is_bot_name_call("состав вас"))
 def test_recent_bot_followups(self):
  self.assertTrue(is_recent_bot_followup("А почему?", "assistant", 15))
  self.assertTrue(is_recent_bot_followup("А если поставить другого?", "assistant", 30))
  self.assertTrue(is_recent_bot_followup("Да", "assistant", 10))
  self.assertFalse(is_recent_bot_followup("А почему?", "user", 10))
  self.assertFalse(is_recent_bot_followup("А почему?", "assistant", 180))
  self.assertFalse(is_recent_bot_followup("/help", "assistant", 5))
  self.assertFalse(is_recent_bot_followup("Привет всем", "assistant", 5))
 def test_activity_and_cooldown_gate(self):
  self.assertTrue(should_spontaneously_reply("FC Mobile, новый OVR",.2,.1,300))
  self.assertFalse(should_spontaneously_reply("FC Mobile, новый OVR",.2,.9,300))
  self.assertFalse(should_spontaneously_reply("FC Mobile, новый OVR",.2,.1,30))
  self.assertFalse(should_spontaneously_reply("привет",.5,.1,300))
  self.assertFalse(should_spontaneously_reply("FC Mobile, новый OVR",.5,.1,300,previous_role="assistant"))
  self.assertFalse(should_spontaneously_reply("FC Mobile, новый OVR",.5,.1,300,reply_to_human=True))
  self.assertFalse(should_spontaneously_reply("да",.5,.1,300))
if __name__=="__main__": unittest.main()
