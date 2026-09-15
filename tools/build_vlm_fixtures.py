#!/usr/bin/env python3
"""Build deterministic visual QA fixtures. Ground truth is NOT sent to models."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def build(out):
    assets = out / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    # Scale Pillow's bundled bitmap font; no external font or package install needed.
    font, title, small = 22, 30, 18
    class Drawing:
        def __init__(self, im):
            self.im, self.draw = im, ImageDraw.Draw(im)
        def __getattr__(self, name):
            return getattr(self.draw, name)
        def text(self, xy, text, font, fill):
            mask = Image.new('L', (max(1, len(text))*8, 16))
            ImageDraw.Draw(mask).text((0,0), text, font=ImageFont.load_default(), fill=255)
            # Fixed line box preserves spaces and consistent character scale.
            mask = mask.crop((0,0,max(1,len(text))*6,12))
            mask = mask.resize((round(mask.width*font/12), font), 0)
            self.im.paste(fill, tuple(map(int,xy)), mask)
    def canvas(size, heading):
        im = Image.new('RGB', size, '#f7f9fc')
        d = Drawing(im)
        d.text((25, 15), heading, font=title, fill='#172338')
        return im, d

    im, d = canvas((900, 650), 'Quarterly sales (units)')
    for val in range(0, 101, 20):
        y = 530 - val * 4
        d.line((90, y, 860, y), fill='#cdd3dd', width=1)
        d.text((40, y-11), str(val), font=small, fill='#333333')
    for i, (a, b) in enumerate(zip([40, 65, 55, 90], [50, 45, 70, 60])):
        x = 150 + i * 185
        for offset, val, color in ((0, a, '#2463ce'), (63, b, '#f29b28')):
            d.rectangle((x+offset, 530-val*4, x+offset+48, 530), fill=color)
            d.text((x+offset+8, 500-val*4), str(val), font=font, fill='#172338')
        d.text((x+30, 548), 'Q'+str(i+1), font=font, fill='#172338')
    d.rectangle((230, 600, 252, 622), fill='#2463ce')
    d.text((265, 599), 'Alpha', font=font, fill='#172338')
    d.rectangle((455, 600, 477, 622), fill='#f29b28')
    d.text((490, 599), 'Beta', font=font, fill='#172338')
    im.save(assets / 'chart.png')

    im, d = canvas((1100, 650), 'Compute console / Select an instance')
    d.rounded_rectangle((25, 75, 1075, 128), radius=8, fill='#dfebfc')
    d.text((45, 90), 'Region: Singapore        Project: VisionLab        Credit: $24.80', font=font, fill='#172338')
    xs = [55, 245, 415, 595, 820]
    for x, txt in zip(xs, ['Instance', 'VRAM', 'Price / hour', 'Status', 'Selection']):
        d.text((x, 162), txt, font=font, fill='#172338')
    rows = [('A17', '24 GB', '$0.42', 'Busy', False), ('B28', '48 GB', '$0.88', 'Ready', False),
            ('C39', '24 GB', '$0.57', 'Ready', True), ('D46', '16 GB', '$0.31', 'Ready', False)]
    for i, row in enumerate(rows):
        y = 210 + i * 72
        d.rounded_rectangle((30, y-10, 1070, y+50), radius=6, fill='#e6efff' if row[4] else 'white', outline='#b7c6dc')
        for x, txt in zip(xs, row[:4]):
            d.text((x, y+6), txt, font=font, fill='#152033')
        d.ellipse((845, y+5, 867, y+27), outline='#275bc4', width=2)
        if row[4]: d.ellipse((851, y+11, 861, y+21), fill='#275bc4')
    d.rectangle((40, 520, 61, 541), outline='#667788', width=2)
    d.text((76, 519), 'I accept the terms', font=font, fill='#172338')
    d.rounded_rectangle((780, 515, 1040, 565), radius=7, fill='#d4d6da')
    d.text((805, 529), 'Launch (disabled)', font=small, fill='#666a70')
    d.text((40, 590), 'Launch requires an available instance and acceptance of the terms.', font=small, fill='#35465f')
    im.save(assets / 'ui.png')

    for state in ['before', 'after']:
        im, d = canvas((640, 640), state.upper() + ' / object board')
        for i, col in enumerate('ABC'):
            d.text((177+i*160, 70), col, font=title, fill='#172338')
        for j in range(3):
            d.text((50, 167+j*160), str(j+1), font=title, fill='#172338')
        for i in range(4):
            d.line((110+i*160, 110, 110+i*160, 590), fill='#8d9bae', width=2)
            d.line((110, 110+i*160, 590, 110+i*160), fill='#8d9bae', width=2)
        def center(cell):
            return 190 + 'ABC'.index(cell[0])*160, 190 + (int(cell[1])-1)*160
        x,y=center('A1' if state == 'before' else 'B1')
        d.ellipse((x-42,y-42,x+42,y+42), fill='#de2838')
        x,y=center('C1'); d.rectangle((x-40,y-40,x+40,y+40), fill='#169850')
        x,y=center('B2' if state == 'before' else 'B3')
        d.polygon([(x,y-46),(x-47,y+37),(x+47,y+37)], fill='#2864de')
        x,y=center('A3')
        d.polygon([(x,y-50),(x+14,y-15),(x+50,y-15),(x+22,y+8),(x+34,y+44),
                   (x,y+23),(x-34,y+44),(x-22,y+8),(x-50,y-15),(x-14,y-15)], fill='#e9b817')
        if state == 'before':
            x,y=center('C3'); d.polygon([(x,y-48),(x+42,y),(x,y+48),(x-42,y)], fill='#9a43be')
        im.save(assets / (state+'.png'))

    prefix = 'Examine only the supplied image(s). Return a single JSON object, without explanation. '
    tasks = [
        {'id':'photo', 'images':['photo.png'], 'prompt':prefix +
         'Use these keys: cats (integer count of visible cats); remote_controls (integer count); '
         'furniture (sofa/bed/chair/table); setting (indoors/outdoors); visible_people (integer); '
         'remote_between_cats (boolean: is one remote located between the cats); '
         'exact_capture_time (HH:MM only if visibly documented; otherwise unknown).',
         'expected':{'cats':2,'remote_controls':2,'furniture':'sofa','setting':'indoors','visible_people':0,
                     'remote_between_cats':True,'exact_capture_time':'unknown'}},
        {'id':'chart','images':['chart.png'],'prompt':prefix +
         'Read the bar chart and legend. Keys: alpha_q2 (integer); beta_peak_quarter (Q1/Q2/Q3/Q4); '
         'alpha_total (integer across all quarters); beta_total (integer); '
         'alpha_q4_minus_beta_q4 (integer); alpha_below_beta_quarters (array of quarter labels in chronological order); '
         'largest_combined_quarter (Q1/Q2/Q3/Q4).',
         'expected':{'alpha_q2':65,'beta_peak_quarter':'Q3','alpha_total':250,'beta_total':225,
                     'alpha_q4_minus_beta_q4':30,'alpha_below_beta_quarters':['Q1','Q3'],'largest_combined_quarter':'Q4'}},
        {'id':'ui','images':['ui.png'],'prompt':prefix +
         'Interpret the console screenshot. Keys: selected_instance (ID); selected_price_per_hour (number); '
         'cheapest_ready_at_least_24gb (ID); launch_enabled (boolean); terms_accepted (boolean); '
         'selected_cost_for_6_hours (number, no discounts); region (string).',
         'expected':{'selected_instance':'C39','selected_price_per_hour':0.57,'cheapest_ready_at_least_24gb':'C39',
                     'launch_enabled':False,'terms_accepted':False,'selected_cost_for_6_hours':3.42,'region':'Singapore'}},
        {'id':'spatial','images':['before.png','after.png'],'prompt':prefix +
         'The first image is BEFORE; the second is AFTER. Grid cells use column letter plus row number. '
         'Keys: red_circle_after (cell); blue_triangle_before (cell); blue_triangle_after (cell); '
         'removed_object (color and shape in two lowercase English words); moved_surviving_objects (integer count); '
         'objects_after (integer count); yellow_star_left_of_blue_triangle_after (boolean).',
         'expected':{'red_circle_after':'B1','blue_triangle_before':'B2','blue_triangle_after':'B3',
                     'removed_object':'purple diamond','moved_surviving_objects':2,'objects_after':4,
                     'yellow_star_left_of_blue_triangle_after':True}}
    ]
    for t in tasks:
        t['image_sha256'] = {name:hashlib.sha256((assets/name).read_bytes()).hexdigest() for name in t['images']}
    manifest = {'tasks':tasks,'photo_source':'https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/coco_sample.png',
                'photo_note':'Public COCO example; original third-party photograph. Other fixtures generated by this script.',
                'methodology':'7 objective fields/task; four tasks; no ground truth or descriptive filenames sent to models.'}
    (out/'fixtures.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print('FIXTURES_READY', out)


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output-dir', type=Path, required=True)
    build(p.parse_args().output_dir)
