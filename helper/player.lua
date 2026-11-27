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
    local now = os.time()
    local deadline = tonumber(state.deadline)
    local left = deadline and math.max(0, math.ceil(deadline - now)) or nil
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
    -- Only the row region fades; the header, footer and clocks remain stationary.
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
        local page_fade = 0
        if board_started then
            local elapsed = mp.get_time() - board_started
            if elapsed >= .18 and board_pending then
                board_visible, board_pending = board_pending, nil
            end
            if elapsed < .36 then
                page_fade = math.floor(255 * (1 - math.abs(elapsed - .18) / .18))
            else
                board_started = nil
            end
        end

        local info = board_visible
        local g = info.geometry
        local u = g.unit
        local portrait = lh > lw
        local navy, gold, white = '723E00', '43B1DE', 'FFFFFF'
        local ink, muted, tint = '2D2925', '6B6156', 'F2F9FC'
        local gutter = lw * (portrait and .04 or .03)
        local available = lw - 2*gutter
        local columns = portrait and {0, .15, .30, .74, 1} or {0, .12, .26, .76, 1}
        local padding = portrait and u or .8*u
        local function cell(index) return gutter + available*columns[index] + padding end
        local function cell_width(index)
            return available * (columns[index+1] - columns[index]) - 2*padding
        end

        -- Navy Banner / Standard / None from the approved HTML review.
        box(0,0,lw,lh,white,'00')
        box(0,0,lw,g.banner,navy,'00')
        local clock_width = u * (portrait and 19 or 12)
        local clock_size = u * (portrait and 3.6 or 2.2)
        local title_size = u * (portrait and 4.6 or 2.7)
        local title_width = available - 2*clock_width - 2*u
        title_size = math.min(title_size, title_width / 10)
        text(gutter,g.banner*.17,'Today’s Screens',title_size,white,7,true)
        text(gutter,g.banner*.69,info.date,u*(portrait and 2 or 1.13),white,7)
        local function clock(x, label, timestamp)
            local parts = os.date('!*t', timestamp)
            local hour = parts.hour % 12
            local value = string.format('%d:%02d %s', hour == 0 and 12 or hour,
                                        parts.min, parts.hour < 12 and 'AM' or 'PM')
            text(x,g.banner*.24,label,u*(portrait and 1.45 or .85),gold,7,true)
            text(x,g.banner*.43,value,clock_size,white,7)
        end
        clock(lw-gutter-2*clock_width,'GMT+5:30',now+19800)
        clock(lw-gutter-clock_width,'GMT',now)

        local rows = info.rows or {}
        if #rows == 0 then
            text(lw/2,lh/2-24*scale,'No presentations scheduled.',32*scale,navy,5,false)
            text(lw/2,lh/2+24*scale,'Sessions from all screens appear here.',18*scale,muted,5)
        else
            box(gutter,g.top,available,g.headings,gold,'00')
            local heading_size = u * (portrait and 1.37 or .85)
            for i, label in ipairs({'SCREEN','PAPER ID','PAPER / AUTHOR','TIME (GMT+5:30)'}) do
                text(cell(i),g.top+g.headings/2,label,heading_size,navy,4,true)
            end

            fade = page_fade
            local striped = false
            for i, row in ipairs(rows) do
                local y = g.top + g.headings + (i-1)*g.row_height
                local cy = y + g.row_height/2
                if row.screen_span > 0 then
                    striped = not striped
                    local group_height = g.row_height*row.screen_span
                    if striped then box(gutter,y,available,group_height,tint,'00') end
                    local center_x = gutter + available*columns[2]/2
                    local center_y = y + group_height/2
                    local badge_width = u * (portrait and 8.2 or 5.1)
                    local badge_height = u * (portrait and 6 or 3.5)
                    local number = row.screen
                    if number:match('^%d$') then number = '0' .. number end
                    local badge_size = u * (portrait and 3.6 or 2)
                    badge_size = math.min(badge_size, (badge_width-u) / math.max(1,#number) / .66)
                    box(center_x-badge_width/2,center_y-badge_height/2,badge_width,badge_height,gold,'00')
                    text(center_x,center_y,number,badge_size,navy,5,true)
                end

                local paper_size = u * (portrait and 2.4 or 1.2)
                text(cell(2),cy,fit(row.paper,cell_width(2),paper_size),paper_size,ink,4)
                local title_font = u * (portrait and 2.4 or 1.2)
                local author_font = u * (portrait and 1.95 or 1)
                local title = fit(row.title,cell_width(3),title_font)
                local author = fit(row.author,cell_width(3),author_font)
                if portrait and title ~= row.title then
                    local prefix = title:gsub('…$', '')
                    local first = prefix:match('^(.*)%s+%S*$') or prefix
                    local rest = row.title:sub(#first+1):gsub('^%s+', '')
                    text(cell(3),cy-2.5*u,first,title_font,ink,4,true)
                    text(cell(3),cy,fit(rest,cell_width(3),title_font),title_font,ink,4,true)
                    text(cell(3),cy+2.6*u,author,author_font,muted,4)
                else
                    local gap = u * (portrait and 1.6 or .9)
                    text(cell(3),cy-gap,title,title_font,ink,4,true)
                    text(cell(3),cy+gap,author,author_font,muted,4)
                end

                local time_size = u * (portrait and 2 or 1.2)
                local time_chars = #(row.session:gsub('–','-'))
                time_size = math.min(time_size, cell_width(4)/math.max(1,time_chars)/.64)
                local date_gap = row.session_date ~= '' and u*(portrait and 1.4 or .8) or 0
                text(cell(4),cy-date_gap,row.session,time_size,navy,4,true)
                if date_gap > 0 then
                    local date_size = u*(portrait and 1.55 or .86)
                    text(cell(4),cy+date_gap,fit(row.session_date,cell_width(4),date_size),date_size,muted,4)
                end
            end
            fade = 0
        end
        local meta_y = lh-footer_height-g.meta/2
        local meta_size = u*(portrait and 1.55 or .84)
        text(gutter,meta_y,fit(info.notice,available*.60,meta_size),meta_size,muted,4)
        text(lw-gutter,meta_y,info.label,meta_size,muted,6)
    end
    -- Thin, fixed footer: screen at left, paper in the center, access URL at right.
    local center_y = lh-footer_height/2
    box(0,lh-footer_height,lw,footer_height,'FAFAFA','00')
    if not state.information then
        box(0,lh-footer_height,lw,math.max(1,math.floor(scale)),'DAD8D4','00')
    end
    local padding = 32*scale
    local paper = state.information and 'Session directory' or ('Paper ID  ' .. (state.paper_id or ''))
    if not state.paper_id and state.footer_left then paper=state.footer_left end
    local address = state.access_url or state.footer_right or ''
    local screen = 'Screen no.  ' .. (state.screen_number or '—')
    local function footer_text(x,value,alignment,width,preferred)
        if state.information then
            local size = math.min(preferred*scale, width/math.max(1,#value)/.66)
            text(x,center_y,value,size,'3B3630',alignment,true)
            return
        end
        local size = math.min(preferred*scale, width/math.max(1,#tostring(value))/.62)
        size = math.max(12*scale,size)
        text(x,center_y,fit(value,width,size),size,'3B3630',alignment,true,'DejaVu Sans')
    end
    footer_text(padding,screen,4,lw*.29,state.information and 19 or 24)
    footer_text(lw/2,paper,5,lw*.34,state.information and 19 or 26)
    footer_text(lw-padding,address,6,lw*.29-padding,state.information and 15 or 20)
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
            local dot_scale = 100*scale
            local dot = 'm 0 7 b 0 3 3 0 7 0 11 0 14 3 14 7 14 11 11 14 7 14 3 14 0 11 0 7'
            lines[#lines+1] = '{' .. tags(x,y,5) ..
                string.format('\\fscx%.2f\\fscy%.2f\\1c&H2727EE&\\3c&HFFFFFF&\\bord%.2f\\p1}',
                    dot_scale, dot_scale, math.max(1, scale)) .. dot .. '{\\p0}'
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

-- Opt-in laptop test. Read only pointer motion inside the mpv window and
-- sample at the receiver's approximate motion rate.
if os.getenv('EPOSTER_TOUCHPAD_AIM') == '1' then
    local last = nil
    local function sample()
        local position = mp.get_property_native('mouse-pos')
        if not position or not position.hover then
            last = nil
            return
        end
        if last and (position.x ~= last.x or position.y ~= last.y) then
            send('TOUCHPAD_AIM', position.x-last.x, position.y-last.y)
        end
        last = position
    end
    local aim_timer = mp.add_periodic_timer(.02, sample)
    aim_timer:kill()
    local function stop_aim()
        aim_timer:kill()
        last = nil
    end
    mp.add_forced_key_binding('a', 'eposter-touchpad-aim', function(event)
        if event.event == 'up' or event.canceled then
            stop_aim()
        elseif event.event == 'down' then
            last = nil
            send('TOUCHPAD_AIM_START')
            sample()
            aim_timer:resume()
        end
    end, {complex=true})
    mp.observe_property('focused', 'bool', function(_, focused)
        if focused == false then stop_aim() end
    end)
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
