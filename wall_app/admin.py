from django.contrib import admin
from .models import WallSection, HistoricalEvent, UserProfile  # 这里的.代表当前应用目录

admin.site.register(WallSection)
admin.site.register(HistoricalEvent)  # 注册历史事件模型到admin后台
admin.site.register(UserProfile)  # 注册用户个人资料模型到admin后台