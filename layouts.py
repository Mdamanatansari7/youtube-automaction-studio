"""Ninja Studio Clipping's native layout geometry, shared by browser preview and FFmpeg."""
import math

CATALOG = [
    ('stack', 'Face + gameplay', 'Camera above the action'),
    ('bottom', 'Gameplay + face', 'Camera below the action'),
    ('blur', 'Blurred fill', 'Keep the complete source'),
    ('fill', 'Fill screen', 'Full-frame centre crop'),
    ('game', 'Gameplay only', 'Use your selected game area'),
    ('pip_tl', 'Camera top-left', 'Floating selected facecam'),
    ('pip_tr', 'Camera top-right', 'Floating selected facecam'),
    ('pip_bl', 'Camera bottom-left', 'Floating selected facecam'),
    ('pip_br', 'Camera bottom-right', 'Floating selected facecam'),
    ('circle', 'Circle camera', 'Round facecam above gameplay'),
    ('side', 'Side by side', 'Camera and gameplay columns'),
]

ASPECTS={'vertical':(1080,1920),'square':(1080,1080),'portrait':(1080,1350),'landscape':(1920,1080),'threefour':(1080,1440)}

def output_settings(body):
    aspect=str(body.get('aspect','vertical'))
    if aspect not in ASPECTS:raise ValueError('Choose a supported aspect ratio.')
    resolution=int(body.get('resolution',1080));fps=int(body.get('fps') or 0)
    if resolution not in (720,1080,2160) or fps not in (0,24,30,60):raise ValueError('Choose 720, 1080 or 2160 and a supported frame rate.')
    width,height=ASPECTS[aspect];scale=resolution/1080
    return int(width*scale)//2*2,int(height*scale)//2*2,fps

def text_positions(name, top=.32, caption_y=1450, width=1080, height=1920):
    spec=geometry(name,top,width,height)
    cam=next((layer for layer in spec['layers'] if layer['source']=='cam'),None)
    hook_y=260*height/1920;position=caption_y*height/1920
    if cam and cam['y']<100*height/1920:hook_y=cam['y']+cam['h']+30*height/1920
    if name=='side':hook_y=260*height/1920
    if caption_y==1450 and cam and cam['y']>900*height/1920:position=min(position,cam['y']-120*height/1920)
    return {'hook_y':round(hook_y),'caption_y':round(position)}

def geometry(name, top=.32, width=1080, height=1920):
    if name not in {x[0] for x in CATALOG}:raise ValueError('Choose a valid layout.')
    top=float(top)
    if not math.isfinite(top) or not .2<=top<=.5:raise ValueError('Face size must be between 20% and 50%.')
    h=int(top*height)//2*2
    full={'source':'full','x':0,'y':0,'w':width,'h':height};game={**full,'source':'game'}
    if name=='blur':return {'mode':'blur','layers':[],'width':width,'height':height}
    if name in ('fill','game'):layers=[full if name=='fill' else game]
    elif name in ('stack','bottom'):
        cam={'source':'cam','x':0,'y':0 if name=='stack' else height-h,'w':width,'h':h}
        layers=[{**game,'y':h if name=='stack' else 0,'h':height-h},cam]
    elif name=='side':
        w=int(top*width)//2*2;layers=[{**game,'x':w,'w':width-w},{'source':'cam','x':0,'y':0,'w':w,'h':height}]
    else:
        # A wide output must not make a square facecam taller than the frame.
        w=min(int(top*width)//2*2,int(height*.45)//2*2)
        size=w if name=='circle' else int(w*.9)//2*2
        margin=int(width*36/1080)//2*2
        layers=[game,{'source':'cam','x':width-w-margin if name in ('pip_tr','pip_br') else margin,
            'y':height-size-round(180*height/1920) if name in ('pip_bl','pip_br') else round(72*height/1920),
            'w':w,'h':size,'circle':name=='circle'}]
    return {'mode':'layers','layers':layers,'width':width,'height':height}

def render_graph(name, rects, top=.32, width=1080, height=1920, cam_fx='', custom_cam=False, cam_input='[1:v]'):
    spec = geometry(name, top, width, height)
    if spec['mode'] == 'blur':
        bw,bh=max(2,width//8*2),max(2,height//8*2)
        base_blur = f'[0:v]split=2[b][f];[b]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},boxblur=8:2,scale={width}:{height}[bg];[f]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1'
        if custom_cam:
            w=min(int(top*width)//2*2,int(height*.45)//2*2)
            size=int(w*.9)//2*2
            margin=int(width*36/1080)//2*2
            cw, ch = w, size
            cx, cy = width - cw - margin, round(72*height/1920)
            return f'{base_blur}[blur_base];{cam_input}scale={cw}:{ch}:force_original_aspect_ratio=increase:flags=lanczos,crop={cw}:{ch},setsar=1{cam_fx}[p_cam];[blur_base][p_cam]overlay={cx}:{cy}:shortest=1[base]'
        return f'{base_blur}[base]'

    layers = list(spec['layers'])
    if custom_cam and not any(l.get('source') == 'cam' for l in layers):
        w=min(int(top*width)//2*2,int(height*.45)//2*2)
        size=int(w*.9)//2*2
        margin=int(width*36/1080)//2*2
        layers.append({'source':'cam','x':width-w-margin,'y':round(72*height/1920),'w':w,'h':size,'circle':False})

    source_layers = [l for l in layers if not (l.get('source') == 'cam' and custom_cam)]
    parts = []
    if len(source_layers) > 1:
        parts.append('[0:v]split=' + str(len(source_layers)) + ''.join(f'[s{i}]' for i in range(len(source_layers))))

    s_idx = 0
    for i, layer in enumerate(layers):
        is_cam = (layer.get('source') == 'cam')
        w, h = layer['w'], layer['h']
        mask = ''
        if layer.get('circle'):
            mask = ",format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(min(W,H)/2,2)),255,0)'"
        look = cam_fx if is_cam else ''

        if is_cam and custom_cam:
            parts.append(f'{cam_input}scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1{look}{mask}[p{i}]')
        else:
            source = f'[s{s_idx}]' if len(source_layers) > 1 else '[0:v]'
            s_idx += 1
            crop = ''
            if layer['source'] != 'full':
                x, y, rw, rh = rects[0 if is_cam else 1]
                crop = f'crop={rw}:{rh}:{x}:{y},'
            parts.append(f'{source}{crop}scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1{look}{mask}[p{i}]')

    first = layers[0]
    parts.append(f"[p0]pad={width}:{height}:{first['x']}:{first['y']}:black[b0]")
    for i, layer in enumerate(layers[1:], 1):
        parts.append(f"[b{i-1}][p{i}]overlay={layer['x']}:{layer['y']}:shortest=1[b{i}]")
    parts.append(f'[b{len(layers)-1}]null[base]')
    return ';'.join(parts)
