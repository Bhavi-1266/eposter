-- Countdown and input live in the same window as all media. No Tk/X11 overlay.
local mp = require 'mp'
local utils = require 'mp.utils'
local state = {rotation = 0, footer_left = '', footer_right = '', status = ''}
local overlay = mp.create_osd_overlay('ass-events')
local previous = ''
local board_visible, board_pending, board_started = nil, nil, nil

local function escape(text)
    return tostring(text or ''):gsub('\\', '\\' .. '\239\187\191'):gsub('{', '\\{'):gsub('}', '\\}'):gsub('\n', '\\N')
end

local function render()
    local deadline = tonumber(state.deadline)
    local left = deadline and math.max(0, math.ceil(deadline - os.time())) or nil
    local countdown = left and tostring(left) or ''
    if countdown ~= state.last_countdown then
        mp.commandv('script-message', 'eposter-state', 'countdown', countdown)
        state.last_countdown = countdown
    end
    local w, h = mp.get_osd_size()
    if not w or w <= 0 or h <= 0 then return end
    local rotation = tonumber(state.rotation) or 0
    local lw, lh = w, h
    if rotation == 90 or rotation == 270 then lw, lh = h, w end
    -- Keep in sync with overlay_scale/uncover_overlays in display_handler.py.
    local scale = math.max(0.75, math.min(w, h) / 1080)
    local lines = {}
    local fade = 0
    local function position(x, y)
        if rotation == 90 then return w-y, x end
        if rotation == 180 then return w-x, h-y end
        if rotation == 270 then return y, h-x end
        return x, y
    end
    local function tags(x, y, alignment)
        local px, py = position(x, y)
        return string.format('\\rDefault\\fscx100\\fscy100\\an%d\\pos(%.2f,%.2f)\\frz%d\\bord0\\shad0\\alpha&H%02X&', alignment or 7, px, py, -rotation, fade)
    end
    local function text(x, y, value, size, color, alignment, bold, font)
        lines[#lines+1] = '{' .. tags(x,y,alignment) .. '\\fn' .. (font or 'DejaVu Sans') .. '\\b' .. (bold and '1' or '0') .. '\\fs' .. size .. '\\1c&H' .. color .. '&}' .. escape(value)
    end
    local function box(x, y, width, height, color, alpha, radius)
        local r = radius or 0
        local path = string.format('m %d 0 l %d 0 b %d 0 %d 0 %d %d l %d %d b %d %d %d %d %d %d l %d %d b 0 %d 0 %d 0 %d l 0 %d b 0 0 0 0 %d 0',
            r,width-r,width,width,width,r,width,height-r,width,height,width,height,width-r,height,r,height,height,height,height-r,r,r)
        local opacity = string.format('%02X', math.max(fade, tonumber(alpha,16) or 0))
        lines[#lines+1] = '{' .. tags(x,y) .. '\\1c&H' .. color .. '&\\1a&H' .. opacity .. '&\\p1}' .. path .. '{\\p0}'
    end
    -- Light information board is an application-local overlay on a white still.
    -- Only the row region fades; the header, footer and clock remain stationary.
    local function fit(value, width, size)
        local chars = {}
        for c in tostring(value or ''):gmatch('[%z\1-\127\194-\244][\128-\191]*') do chars[#chars+1] = c end
        local limit = math.max(1, math.floor(width / (size * .66)))
        if #chars > limit then
            return table.concat(chars, '', 1, math.max(1,limit-1)) .. '…'
        end
        return table.concat(chars)
    end
    local footer_height = math.floor(48*scale + .5)
    if state.information and board_visible then
        local info = board_visible
        box(0,0,lw,lh,'FFFFFF','00')
        local gutter = lw*.03
        text(gutter,gutter,'EPOSTER / SESSION DIRECTORY',14*scale,'6E6760',7,false,'DejaVu Sans')
        text(gutter,gutter+24*scale,fit('Match your paper and author to a screen.',lw*.68,18*scale),18*scale,'736B61',7,false,'DejaVu Sans')
        text(lw-gutter,gutter,os.date('%H:%M'),42*scale,'2D2925',9)
        text(lw-gutter,gutter+54*scale,os.date('%d %b %Y'),15*scale,'736B61',9,false,'DejaVu Sans')
        if board_started then
            local elapsed = mp.get_time()-board_started
            if elapsed < .18 then
                fade = math.floor(255*elapsed/.18)
            else
                if board_pending then board_visible = board_pending; board_pending = nil end
                info = board_visible
                fade = math.max(0,math.floor(255*(1-(elapsed-.18)/.18)))
                if elapsed >= .36 then board_started = nil; fade = 0 end
            end
        end
        local g = info.geometry
        local top = g.top
        local available = lw-2*gutter
        local portrait = lh>lw
        local columns = portrait and {0,.14,.32,.79} or {0,.12,.29,.68,.86}
        local headings = portrait and {'SCREEN','PAPER ID','AUTHOR / PAPER','STATUS'}
                          or {'SCREEN','PAPER ID','AUTHOR / PAPER','SESSION','STATUS'}
        fade = 0
        for i, heading in ipairs(headings) do
            text(gutter+available*columns[i]+12*scale,top,heading,13*scale,'6A6359',7,true,'DejaVu Sans')
        end
        box(gutter,top+g.headings-2*scale,available,2*scale,'B8B2AA','00')
        if board_started then
            local elapsed = mp.get_time()-board_started
            fade = math.max(0,math.min(255,math.floor(255*(elapsed<.18 and elapsed/.18 or 1-(elapsed-.18)/.18))))
        end
        for i, row in ipairs(info.rows or {}) do
            local y = top+g.headings+(i-1)*g.row_height
            local cy = y+g.row_height/2
            if i%2==1 then box(gutter,y,available,g.row_height,'F5F4F2','00') end
            box(gutter,y+g.row_height-1,available,1,'E1DED9','00')
            local function cell(index) return gutter+available*columns[index]+12*scale end
            local badge = math.min(available*.09,82*scale)
            box(cell(1),cy-29*scale,badge,58*scale,'D4CFC7','00')
            box(cell(1)+1,cy-29*scale+1,badge-2,58*scale-2,'EFEDE9','00')
            text(cell(1)+badge/2,cy,fit(row.screen,badge-10*scale,30*scale),30*scale,'413A30',5)
            text(cell(2),cy,fit(row.paper,available*(columns[3]-columns[2])-20*scale,22*scale),22*scale,'3B3630',4,false,'DejaVu Sans')
            local author_width=available*(columns[4]-columns[3])-24*scale
            text(cell(3),cy-14*scale,fit(row.author,author_width,22*scale),22*scale,'3B3630',4,false,'DejaVu Sans')
            text(cell(3),cy+17*scale,fit(row.title,author_width,16*scale),16*scale,'726B60',4,false,'DejaVu Sans')
            if not portrait then text(cell(4),cy,row.session,20*scale,'3B3630',4,false,'DejaVu Sans') end
            local starts = tostring(row.status):match('^Starts in (%d+) min$')
            if starts and portrait then
                text(cell(#columns),cy-12*scale,'Starts in',18*scale,'5E574C',4,false,'DejaVu Sans')
                text(cell(#columns),cy+12*scale,starts .. ' min',18*scale,'5E574C',4,false,'DejaVu Sans')
            else
                text(cell(#columns),cy,fit(row.status,available*(1-columns[#columns])-16*scale,18*scale),18*scale,'5E574C',4,false,'DejaVu Sans')
            end
        end
        fade = 0
        if #(info.rows or {})==0 then
            text(lw/2,lh/2-24*scale,'No presentations scheduled.',32*scale,'3B3630',5,false,'DejaVu Sans')
            text(lw/2,lh/2+24*scale,'Running sessions and those starting within 5 minutes appear here.',18*scale,'736B61',5,false,'DejaVu Sans')
        end
        local my = lh-footer_height-g.meta/2
        text(gutter,my,fit(info.notice,available*.60,15*scale),15*scale,'736B61',4,false,'DejaVu Sans')
        text(lw-gutter,my,info.label,15*scale,'736B61',6,false,'DejaVu Sans')
    end
    -- Thin, fixed footer: screen at left, paper in the center, access URL at right.
    local center_y = lh-footer_height/2
    box(0,lh-footer_height,lw,footer_height,'FAFAFA','00')
    box(0,lh-footer_height,lw,math.max(1,math.floor(scale)),'DAD8D4','00')
    local padding = 32*scale
    local paper = state.information and 'Session directory' or ('Paper ID  ' .. (state.paper_id or ''))
    if not state.paper_id and state.footer_left then paper=state.footer_left end
    local address = state.access_url or state.footer_right or ''
    local screen = 'Screen no.  ' .. (state.screen_number or '—')
    local function footer_text(x,value,alignment,width,preferred)
        local size = math.min(preferred*scale, width/math.max(1,#tostring(value))/.62)
        size = math.max(12*scale,size)
        text(x,center_y,fit(value,width,size),size,'3B3630',alignment,true,'DejaVu Sans')
    end
    footer_text(padding,screen,4,lw*.29,24)
    footer_text(lw/2,paper,5,lw*.34,26)
    footer_text(lw-padding,address,6,lw*.29-padding,20)
    -- Session timer stays live at the top right even while mpv is paused.
    if deadline then
        local value = string.format('%02d:%02d', math.floor(left/60), left%60)
        local tw, th = math.max(96, #value*19)*scale, 36*scale
        local tx, ty = lw-tw-8*scale, 8*scale
        box(tx,ty,tw,th,'D6D2CC','00',2*scale)
        box(tx+1,ty+1,tw-2,th-2,'FFFFFF','00',2*scale)
        text(tx+tw/2,ty+th/2,value,28*scale,'403930',5)
    end
    -- Status only: no click target or on-screen playback button.
    if state.paused and not state.information then
        local x, y = 28*scale, lh-footer_height-72*scale
        box(x,y,42*scale,42*scale,'DAD6D0','00',4*scale)
        box(x+1,y+1,42*scale-2,42*scale-2,'FFFFFF','00',4*scale)
        box(x+14*scale,y+12*scale,5*scale,18*scale,'6A6359','00')
        box(x+23*scale,y+12*scale,5*scale,18*scale,'6A6359','00')
    end
    if state.status and state.status ~= '' then
        local size = math.max(18, math.floor(lw/45))
        local value = tostring(state.status)
        local x = math.max(24, (lw - #value*size*0.6)/2)
        box(0,lh/2-12,lw,size*2.2,'F5F5F5','00',0)
        text(x,lh/2,value,size,'3B3630')
    end
    if state.pointer and state.pointer.x and state.pointer.y then
        local x, y = tonumber(state.pointer.x), tonumber(state.pointer.y)
        if x and y then
            local radius = math.max(12, math.floor(16*scale))
            -- Application-local AIM cursor: high-contrast rings plus crosshair.
            lines[#lines+1] = '{' .. tags(x,y,5) .. '\\1c&H000000&\\3c&H000000&\\bord0\\p1}' ..
                string.format('m %d 0 b %d %d %d %d 0 %d b %d %d %d %d %d 0 m %d %d l %d %d m %d %d l %d %d',
                    radius, radius, 0, radius, radius, radius*2, -radius, radius*2, -radius, 0, radius, 0,
                    -radius-7, radius, radius+7, radius, radius, -7, radius, radius*2+7) .. '{\\p0}'
            lines[#lines+1] = '{' .. tags(x,y,5) .. '\\1c&HFFFFFF&\\3c&HFFFFFF&\\bord0\\p1}' ..
                string.format('m %d 2 b %d %d %d %d 2 %d b %d %d %d %d %d 2',
                    radius, radius-2, 2, radius-2, radius, radius*2-2,
                    -radius+2, radius*2-2, -radius+2, 2, radius, 2) .. '{\\p0}'
        end
    end
    local data = table.concat(lines, '\n')
    local key = data .. w .. ':' .. h
    if key == previous then return end
    previous = key
    overlay.res_x, overlay.res_y, overlay.data = w, h, data
    overlay:update()
end

mp.register_script_message('eposter-overlay', function(json)
    local parsed = utils.parse_json(json)
    if parsed then
        local info = parsed.information
        if info and info ~= utils.null then
            if board_pending and info.generation == board_pending.generation then
                board_pending = info
            elseif board_visible and info.generation == board_visible.generation then
                board_visible = info
            elseif board_visible and info.animate then
                board_pending = info
                if not board_started then board_started = mp.get_time() end
            else
                board_visible = info
                board_pending=nil; board_started=nil
            end
        else
            board_visible=nil; board_pending=nil; board_started=nil
            parsed.information=nil
        end
        state = parsed; previous = ''; render()
    end
end)
mp.observe_property('osd-dimensions', 'native', function() previous = ''; render() end)
local next_idle_render = 0
mp.add_periodic_timer(0.033, function()
    local now = mp.get_time()
    if board_started or now >= next_idle_render then
        render()
        next_idle_render = now + .25
    end
end)

local function send(key, x, y)
    mp.commandv('script-message', 'eposter-input', key, tostring(x or 0), tostring(y or 0))
end
for _, key in ipairs({'q','ESC','ENTER','SPACE','UP','DOWN','PGUP','PGDWN','WHEEL_UP','WHEEL_DOWN'}) do
    mp.add_forced_key_binding(key, 'eposter-' .. key, function() send(key) end, {repeatable=key ~= 'SPACE'})
end
for _, key in ipairs({'m', 'M'}) do
    mp.add_forced_key_binding(key, 'eposter-menu-' .. key, function() send('M') end)
end
local press = nil
mp.add_forced_key_binding('MBTN_LEFT', 'eposter-click', function(event)
    local x, y = mp.get_mouse_pos()
    if event.event == 'down' then
        press = {x=x, y=y}
    elseif event.event == 'up' then
        if press and math.abs(y-press.y) + math.abs(x-press.x) > 15 then
            send('DRAG', x-press.x, y-press.y)
        else
            send('CLICK', x, y)
        end
        press = nil
    elseif event.event == 'press' then
        send('CLICK', x, y)
    end
end, {complex=true})
-- Prevent default double click fullscreen toggles and right click actions.
mp.add_forced_key_binding('MBTN_LEFT_DBL', 'eposter-double', function() end)
mp.add_forced_key_binding('MBTN_RIGHT', 'eposter-right', function() send('ESC') end)

mp.register_script_message('eposter-ping', function()
    mp.commandv('script-message', 'eposter-state', 'ready', '1')
end)
