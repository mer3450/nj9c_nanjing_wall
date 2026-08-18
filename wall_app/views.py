from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.conf import settings
from pathlib import Path
import functools
from .models import WallSection, HistoricalEvent, WallFeedback, UserProfile
from .forms import UserRegisterForm, WallSectionForm, createhistoricaleventForm, WallFeedbackForm
from .utils import check_contribution_with_deepseek  # 导入内容审核函数

def home(request):
    """首页视图"""
    sections = WallSection.objects.select_related('user').all()
    # 方案一：「市民发现」模块 —— 展示带有探究发现的城墙段（最新 5 条），标注「待验证猜想」
    discoveries = WallSection.objects.exclude(discovery__isnull=True).exclude(
        discovery__exact=''
    ).order_by('-created_at')[:5]
    return render(request, 'home.html', {
        'sections': sections,
        'discoveries': discoveries
    })

def section_detail(request, section_id):
    """城墙段落详情视图"""
    section = get_object_or_404(WallSection, id=section_id)
    events = HistoricalEvent.objects.filter(wall_section=section)
    # 方案三：互证与质疑反馈列表（select_related 避免逐条查询 user）
    feedbacks = WallFeedback.objects.filter(
        wall_section=section
    ).select_related('user').order_by('-created_at')
    # 两个独立表单：补充证据 / 不同看法
    evidence_form = WallFeedbackForm(initial={'feedback_type': 'evidence'})
    challenge_form = WallFeedbackForm(initial={'feedback_type': 'challenge'})
    return render(request, 'section_detail.html', {
        'section': section,
        'events': events,
        'feedbacks': feedbacks,
        'evidence_form': evidence_form,
        'challenge_form': challenge_form,
    })

def about_page(request):
    return render(request, 'about.html')

@functools.lru_cache(maxsize=1)
def _load_mer_html():
    """彩蛋页是静态 HTML，缓存到内存，避免每次请求都读 2.5MB 磁盘文件。"""
    return (Path(settings.BASE_DIR) / 'templates' / 'mer.html').read_bytes()

def mer_page(request):
    """彩蛋页面 — 直接返回静态 HTML，不走 Django 模板引擎"""
    return HttpResponse(_load_mer_html(), content_type='text/html; charset=utf-8')

def register(request):
    """用户注册视图"""
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'账户 {username} 创建成功！现在可以登录了。')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'register.html', {'form': form})

def user_login(request):
    """用户登录视图"""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if not username or not password:
            messages.error(request, '请输入用户名和密码。')
            return render(request, 'login.html')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            # 若存在 next 参数（例如从「个人主页」跳转而来），登录后回到原页面；否则回首页
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and next_url.startswith('/'):  # 仅允许站内相对路径，避免开放重定向
                return redirect(next_url)
            return redirect('home')
        else:
            messages.error(request, '用户名或密码错误，请重试。')
            return render(request, 'login.html')
    else:
        return render(request, 'login.html')

def user_logout(request):
    #用户注销视图
    logout(request)
    return redirect('home')

@login_required
def create_contribution(request):
    if request.method!= 'POST':
        # 默认预选「我确定」，让推测理由输入框保持隐藏，避免用户未选择时被表单校验拦截
        form = WallSectionForm(initial={
            'built_year_confidence': 'confirmed',
            'length_confidence': 'confirmed',
        })
        return render(request, 'create_contribution.html', {'form': form})
    else:
        form = WallSectionForm(data=request.POST, files=request.FILES)  # 注意这里要加上 files=request.FILES，因为有文件上传
        if form.is_valid():
            # 准备审核数据
            contribution_data = {
                'name': form.cleaned_data.get('name', ''),
                'location': form.cleaned_data.get('location', ''),
                'description': form.cleaned_data.get('description', ''),
                'built_year': form.cleaned_data.get('built_year', ''),
                'length': form.cleaned_data.get('length', '')
            }
            
            # 调用DeepSeek API审核内容
            is_approved, message = check_contribution_with_deepseek(contribution_data)
            
            if is_approved:
                # 审核通过，保存贡献
                contribution = form.save(commit=False)
                contribution.user = request.user
                contribution.save()
                messages.success(request, '贡献提交成功！内容已通过审核。')
                return redirect('home')
            else:
                # 审核未通过，返回错误信息
                messages.error(request, f'内容审核未通过：{message}')
                return render(request, 'create_contribution.html', {'form': form})
        else:
            return render(request, 'create_contribution.html', {'form': form})
            

@login_required
def create_feedback(request, section_id):
    """方案三：提交互证/质疑反馈，并更新统计与争议状态"""
    section = get_object_or_404(WallSection, id=section_id)

    if request.method == 'POST':
        form = WallFeedbackForm(request.POST, request.FILES)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.user = request.user
            feedback.wall_section = section
            feedback.save()

            # 按「不同用户」去重统计，确保同一用户多次提交只计 1 人
            distinct_challengers = WallFeedback.objects.filter(
                wall_section=section, feedback_type='challenge'
            ).values('user').distinct().count()
            distinct_evidence = WallFeedback.objects.filter(
                wall_section=section, feedback_type='evidence'
            ).values('user').distinct().count()

            section.challenge_count = distinct_challengers
            section.evidence_count = distinct_evidence
            # 被 3 个不同用户质疑时，自动标记为「待考证」
            if distinct_challengers >= 3:
                section.dispute_status = 'pending'
            section.save()

            if feedback.feedback_type == 'challenge':
                messages.success(request, '已提交你的不同看法，感谢参与探究！')
            else:
                messages.success(request, '已补充证据，感谢参与探究！')
        else:
            messages.error(request, '提交失败，请检查表单内容后重试。')
        return redirect('section_detail', section_id=section.id)

    # GET 请求直接跳回详情页
    return redirect('section_detail', section_id=section.id)


@login_required
def user_contributions(request):
    """用户贡献列表视图（新城墙段统一以 WallSection 形式展示）"""
    sections = WallSection.objects.filter(user=request.user)
    return render(request, 'user_contributions.html', {'sections': sections})

@login_required
def user_profile(request, user_id=None):
    if user_id is None:
        user = request.user
    else:
        user = get_object_or_404(User, pk=user_id)
    # 确保该用户有对应的 UserProfile，否则模板中访问 user.userprofile 会抛 500
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return render(request, 'user_profile.html', {
        'user': user,
        'profile': profile,
    })
def map_view(request):
    """地图视图"""
    sections = WallSection.objects.all()
    return render(request, 'map.html', {'sections': sections})
def history_view(request):
    """历史事件视图"""
    # year 是 CharField（可能含「明代」「约1366」等非纯数字），直接 order_by 会按字符串排序，
    # 导致时间线错乱。这里在 Python 层按数值年份降序排列，非数字年份排到最后。
    history = list(HistoricalEvent.objects.all())
    history.sort(
        key=lambda e: int(e.year) if (e.year or '').strip().isdigit() else 9999,
        reverse=True,
    )
    return render(request, 'history.html', {'history': history})
def picture_gallery(request):
    """图片画廊视图"""
    sections = WallSection.objects.all()
    return render(request, 'picture_gallery.html', {'sections': sections})
@login_required
def create_historical_event(request):
    """创建历史事件视图"""
    if request.method != 'POST':
        form = createhistoricaleventForm()
        return render(request, 'create_historical_event.html', {'form': form})
    else:
        form = createhistoricaleventForm(request.POST)
        if form.is_valid():
            form.save()  # wall_section 已由表单字段携带，直接保存
            return redirect('home')
        else:
            return render(request, 'create_historical_event.html', {'form': form})
def custom_404(request, exception):
    """自定义404错误页面视图"""
    return render(request, 'errors/404.html', status=404)
def custom_500(request):
    """自定义500错误页面视图"""
    return render(request, 'errors/500.html', status=500)
def custom_403(request, exception):
    """自定义403错误页面视图"""
    return render(request, 'errors/403.html', status=403)
def custom_400(request, exception):
    """自定义400错误页面视图"""
    return render(request, 'errors/400.html', status=400)