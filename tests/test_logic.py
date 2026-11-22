import unittest
from app.logic import is_fc_topic,is_direct_message,should_spontaneously_reply
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
 def test_activity_and_cooldown_gate(self):
  self.assertTrue(should_spontaneously_reply("FC Mobile, новый OVR",.2,.1,300))
  self.assertFalse(should_spontaneously_reply("FC Mobile, новый OVR",.2,.9,300))
  self.assertFalse(should_spontaneously_reply("FC Mobile, новый OVR",.2,.1,30))
  self.assertFalse(should_spontaneously_reply("привет",.5,.1,300))
if __name__=="__main__": unittest.main()
