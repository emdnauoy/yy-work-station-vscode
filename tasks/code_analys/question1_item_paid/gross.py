
def update_erp_history_order(start_day, end_day):
    """
    1、拿yy_erp_qianyiapi_history表的订单去千易备库找对应关系，拿sku_id, spu_id， 更新到db
    2、data_platform_order表拿商品实付、平台卖家补贴、商家折扣 分摊给sku
        + 组合品按 成本分摊
    """

    dbconn, cursor = YYDB.new_db_conn('rm-uf61x6v9wnzc1uo2f7o.mysql.rds.aliyuncs.com', 'yaoyao_dev', 3306,'qwedcvfrt1234@')
    # dbconn, cursor = YYDB.new_db_conn()
    # 从千易备库拿拆分后的sku，要过滤掉erp_history表不存在的sku, 比如拆分前的组合品
    qianyi_dbconn, qianyi_cursor = YYDB.new_db_conn(settings.QIANYIDB_HOST, settings.QIANYIDB_USER, 3306, settings.QIANYIDB_PASSWORD)

    # 按天处理
    start_day = datetime.strptime(start_day, "%Y-%m-%d").date()
    end_day = datetime.strptime(end_day, "%Y-%m-%d").date()
    all_month_days = [start_day + timedelta(days=x) for x in range((end_day - start_day).days + 1)]

    # 倒序排序
    all_month_days = sorted(all_month_days, reverse=True)

    # sku实时的采购单价
    purchase_unit_price_dict = fetch_sku_purchase_unit_price([], cursor)

    shops = {v['shopee_shop_id']: v for v in fetch_all_shop_info(dbconn, cursor)}

    for payment_day in all_month_days:
        test_oid = []
        update_order_type = []

        # 日汇率
        day_exchange_rate = fetch_day_exchange_rate(str(payment_day), cursor)

        # 拿付款日期内的spu的平均采购成本
        spu_avg_price = sum_order_spu_skus(str(payment_day), cursor)
        # 切片处理，避免数据量过大
        today_all_oids = fetch_day_all_oids(payment_day, cursor, oids=test_oid)
        logger.info('处理 %s 日订单数: %s' % (payment_day, len(today_all_oids)))

        oid_arr = [today_all_oids[i:i + 10000] for i in range(0, len(today_all_oids), 10000)]
        for oids in oid_arr:
            # 第一步，先统计订单的类型，因为有的订单一个sku都没有。下面程序处理不到
            all_orders = fetch_day_all_erp_oids(payment_day, cursor, oids=oids)

            # 2、data_platform_order表拿商品实付、平台卖家补贴、商家折扣
            platform_orders, platform_order_fees, platform_order_fee_total = fetch_order_detail(list(all_orders.keys()), cursor)

            for oid, order_info in all_orders.items():
                if order_info['shop_id'] not in shops:
                    logger.error('shop_id 在pj表不存在：%s, %s' % (oid, order_info['shop_id']))
                    continue
                shop_info = shops[order_info['shop_id']]
                order_type = 0 if oid in platform_orders else 5
                if oid[-3:] == '_RE':
                    order_type = 4
                elif shop_info['platform'] == '分销' and order_info['pay_amount']:
                    order_type = 1  # 分销
                elif shop_info['platform'] == '分销' and not order_info['pay_amount']:
                    order_type = 3  # 样品
                elif not order_info['online_status']:
                    order_type = 2  # 手工单
                    if not order_info['pay_amount']:  # 订单金额=0的手工单
                        order_type = 3  # 样品
                update_order_type.append({
                    'original_order_number': oid,
                    'order_type': order_type
                })
            update_erp_order_type(update_order_type, cursor, dbconn)

            # 1、拿erp订单
            erp_orders, all_skus, order_shop_id, order_sku_quantity = fetch_day_erp_orders(payment_day, cursor, oids)
            all_oids = list(set(erp_orders.keys()))

            if not all_oids:
                continue

            # 拿采购成本，按天拿，因为用订单支付时间拿前2个月的日志记录
            sku_day_purchase_info = fetch_op_sku_purchase_price_info(str(payment_day), cursor, purchase_unit_price_dict, all_skus)

            # 拿付款日期的sku_level
            sku_level_dict = order_sku_level(str(payment_day), all_skus, cursor)

            # 去千易备库找对应关系，拿sku_id, spu_id， 更新到db, 这里必须先更新 后面才能分摊
            qianyi_orders = fetch_qianyi_db_order_info(all_oids, qianyi_cursor)
            # print('qianyi_orders:', qianyi_orders)

            # 更新db基础字段，sku_id、spu_id
            update_erp_spu_id = []
            erp_ids = []
            not_in_qy_oids = []
            for oid, skus in erp_orders.items():
                if order_shop_id[oid]['shop_id'] not in shops:
                    logger.error('shop_id 在pj表不存在：%s, %s' % (oid, order_shop_id[oid]['shop_id']))
                    continue
                shop_info = shops[order_shop_id[oid]['shop_id']]
                nation = shop_info['nation']

                # 1-从千易备库批不上的订单
                if oid not in qianyi_orders:
                    # 千易备库拿不到就用我们自己的平台订单表和erp_history表的数据去计算, 如果多个sku,则按采购成本分摊
                    order_total_fee = platform_order_fee_total.get(oid, {})
                    # 算成本 按成本分摊
                    total_purchase_price = Decimal(0)
                    for _sku_info in order_sku_quantity.get(oid, []):
                        purchase_info = sku_day_purchase_info.get(_sku_info['sku'], {})
                        purchase_price = Decimal(0)
                        if purchase_info and purchase_info['purchase_cost']:
                            purchase_price = Decimal(purchase_info['purchase_cost']) * Decimal(_sku_info['sku_quantity'])
                        total_purchase_price += purchase_price

                    if order_total_fee:
                        for _sku_info in order_sku_quantity.get(oid, []):
                            try:
                                purchase_info = sku_day_purchase_info.get(_sku_info['sku'], {})
                                purchase_price = Decimal(0)
                                if purchase_info and purchase_info['purchase_cost']:
                                    purchase_price = Decimal(purchase_info['purchase_cost']) * Decimal(_sku_info['sku_quantity'])
                                _rate = purchase_price / total_purchase_price if total_purchase_price else 0
                                # if len(skus) == 1:  # 如果只有一个sku,则不用分摊
                                #     _rate = Decimal(1)
                                original_price = order_total_fee['original_price'] / Decimal(10000) * _rate
                                platform_subsidy = order_total_fee['platform_subsidy'] / Decimal(10000) * _rate
                                paid_price = order_total_fee['item_paid'] / Decimal(10000) * _rate
                                seller_voucher = order_total_fee['seller_voucher'] / Decimal(10000) * _rate
                                platform_shipping_fee = order_total_fee['platform_shipping_fee'] / Decimal(10000) * _rate
                                platform_shipping_fee_discount = order_total_fee['platform_shipping_fee_discount'] / Decimal(10000) * _rate
                                _exchange_rate = day_exchange_rate.get(_sku_info['currency'], 0)
                                item = {
                                    'sku_id': purchase_unit_price_dict.get(_sku_info['sku'], {}).get('yy_sku_id', 0),
                                    'sku_level': sku_level_dict.get(_sku_info['sku'] + '|' + nation, ''),
                                    'purchase_unit_price': purchase_unit_price_dict.get(_sku_info['sku'], {}).get('unit_price', 0),
                                    'spu_avg_purchase_unit_price': spu_avg_price.get(_sku_info['sku'], 0),
                                    'marked_price': original_price,
                                    'platform_subsidy': platform_subsidy,
                                    'paid_price': paid_price,
                                    'seller_voucher': seller_voucher,
                                    'product_cost_cny': purchase_price,
                                    'platform_subsidy_usd': platform_subsidy / _exchange_rate if _exchange_rate else 0,
                                    'paid_price_usd': paid_price / _exchange_rate if _exchange_rate else 0,
                                    'seller_voucher_usd': seller_voucher / _exchange_rate if _exchange_rate else 0,
                                    'product_cost_usd': purchase_price / day_exchange_rate.get(
                                        'CNY', 0) if day_exchange_rate.get('CNY', 0) else 0,
                                    'platform_shipping_fee': platform_shipping_fee,
                                    'platform_shipping_fee_discount': platform_shipping_fee_discount,
                                    'order_sn': oid,
                                    'sku': _sku_info['sku'],
                                    'product_units': _sku_info['sku_quantity'],
                                }
                                not_in_qy_oids.append(item)
                            except Exception as e:
                                logger.error(oid, e)
                                continue
                    else:
                        # 不是平台订单就那erp_history的千易实付做为商品实付
                        for _sku_info in order_sku_quantity.get(oid, []):
                            try:
                                purchase_info = sku_day_purchase_info.get(_sku_info['sku'], {})
                                purchase_price = Decimal(0)
                                if purchase_info and purchase_info['purchase_cost']:
                                    purchase_price = Decimal(purchase_info['purchase_cost']) * Decimal(_sku_info['sku_quantity'])

                                shipping_fee = Decimal(_sku_info['shipping_fee']) if _sku_info['shipping_fee'] else 0
                                paid_price = _sku_info['pay_amount'] - shipping_fee
                                _exchange_rate = day_exchange_rate.get(_sku_info['currency'], 0)
                                item = {
                                    'sku_id': purchase_unit_price_dict.get(_sku_info['sku'], {}).get('yy_sku_id', 0),
                                    'sku_level': sku_level_dict.get(_sku_info['sku'] + '|' + nation, ''),
                                    'purchase_unit_price': purchase_unit_price_dict.get(_sku_info['sku'], {}).get('unit_price', 0),
                                    'spu_avg_purchase_unit_price': spu_avg_price.get(_sku_info['sku'], 0),
                                    'marked_price': 0,
                                    'platform_subsidy': 0,
                                    'paid_price': paid_price,
                                    'seller_voucher': 0,
                                    'product_cost_cny': purchase_price,
                                    'platform_subsidy_usd': 0,
                                    'paid_price_usd': paid_price / _exchange_rate if _exchange_rate else 0,
                                    'seller_voucher_usd': 0,
                                    'product_cost_usd': purchase_price / day_exchange_rate.get('CNY', 0) if day_exchange_rate.get('CNY', 0) else 0,
                                    'platform_shipping_fee': 0,
                                    'platform_shipping_fee_discount': 0,
                                    'order_sn': oid,
                                    'sku': _sku_info['sku'],
                                    'product_units': _sku_info['sku_quantity'],
                                }
                                not_in_qy_oids.append(item)
                            except Exception as e:
                                logger.error('计算非平台订单error: %s, %s' % (oid, e))
                                continue
                    continue

                # 能从千易备库批的上的订单
                _qy_spu_sku = {}
                for online_sku_id, sku_arr in qianyi_orders[oid].items():
                    for sku_one in sku_arr:
                        _key = '%s|%s|%s' % (sku_one['sku'], sku_one['online_sku_code'], sku_one['quantity'])
                        _qy_spu_sku[_key] = online_sku_id

                for unique_key, sku_arr in skus.items():
                    if unique_key not in _qy_spu_sku:
                        logger.error('%s, %s 在千易备库未匹配到数据' % (oid, unique_key))
                    _online_item_id = _qy_spu_sku.get(unique_key, '')
                    online_sku_id = ''
                    online_spu_id = ''
                    if _online_item_id and len(_online_item_id.split('-')) == 2:
                        online_spu_id = _online_item_id.split('-')[0]
                        online_sku_id = _online_item_id.split('-')[1]
                    elif _online_item_id and len(_online_item_id.split('-')) == 1:
                        online_spu_id = _online_item_id.split('-')[0]

                    for sku_item in sku_arr:
                        erp_ids.append(sku_item['erp_id'])
                        update_erp_spu_id.append({
                            'erp_id': sku_item['erp_id'],
                            'brush_or_not_int': 1 if sku_item['brush_or_not'] == '是' else 0,
                            'sku_id': purchase_unit_price_dict.get(sku_item['sku'], {}).get('yy_sku_id', 0),
                            'sku_level': sku_level_dict.get(sku_item['sku'] + '|' + nation, ''),
                            'online_sku_id': online_sku_id,
                            'online_spu_id': online_spu_id if online_spu_id else '',
                            'purchase_unit_price': purchase_unit_price_dict.get(sku_item['sku'], {}).get('unit_price', 0),
                            'spu_avg_purchase_unit_price': spu_avg_price.get(sku_item['sku'], 0),
                            'payment_time_update': payment_day,
                            'order_created_time': str(payment_day - timedelta(days=1)) + ' 00:00:00'
                        })

            update_erp_order_base_fields(update_erp_spu_id, cursor, dbconn)

            ### 二、把平台的钱分给千易订单，如果有组合品，则按采购成本分摊

            new_erp_orders = fetch_erp_orders_by_ids(erp_ids, cursor)
            data = []
            for oid, erp_sku_info in new_erp_orders.items():
                if oid not in qianyi_orders:
                    logger.error('erp订单表 在千易备库 不存在：%s' % oid)
                    continue
                qy_order_dict = qianyi_orders[oid]
                # 非平台订单，不分摊，直接取千易的实付
                if oid not in platform_order_fees:
                    _data = build_not_platform_order_fee(oid, erp_sku_info, sku_day_purchase_info, day_exchange_rate, qy_order_dict)
                else:
                    # 平台订单
                    _data = build_platform_order_fee(oid, erp_sku_info, sku_day_purchase_info, day_exchange_rate,
                                                     qy_order_dict, platform_order_fees[oid])
                data.extend(_data)

            update_erp_orders_fee(payment_day, data, cursor, dbconn)

            if not_in_qy_oids:
                update_not_qy_db_orders_fee(not_in_qy_oids, cursor, dbconn)
    logger.info('end...')
    return


def fetch_erp_orders_by_ids(ids, cursor):
    """
    根据表的自增id找订单
    """
    if not ids:
        return {}
    sql = """
    select erp_id, original_order_number, product_code as sku, system_tracking_number, platform, 
    online_product_code, product_units, shop_id, actual_payment_amount as pay_amount, online_status, currency,  product_units as quantity,
    shipping_fee, online_sku_id, online_spu_id
    from bi.yy_erp_qianyiapi_history 
    where erp_id in %(ids)s
    """
    cursor.execute(sql, {'ids': ids})
    rows = cursor.fetchall()
    erp_orders = {}  # erp订单
    for o in rows:
        if not o['sku']: continue
        if o['original_order_number'] not in erp_orders:
            erp_orders[o['original_order_number']] = {}
        _key = ''
        if o['online_spu_id'] and o['online_sku_id']:
            _key = '%s-%s' % (o['online_spu_id'], o['online_sku_id'])
        elif not o['online_sku_id'] and o['online_spu_id']:
            _key = o['online_spu_id']
        erp_orders[o['original_order_number']].setdefault(_key, []).append(o)
    return erp_orders


def fetch_day_all_oids(payment_day, cursor, oids=[]):
    """
    某天的erp订单
    """
    _where = ''
    if oids:
        _where = " and original_order_number in ('"+"','".join(oids)+"') "
    sql = """
    select distinct original_order_number
    from bi.yy_erp_qianyiapi_history 
    where system_tracking_number = 'S2606067079508' 
    {}
    and order_created_time >= %(created_start)s
    """.format(_where)
    cursor.execute(sql, {
        'payment_day': str(payment_day),
        'created_start': str(payment_day - timedelta(days=1)) + ' 00:00:00'
    })
    rows = cursor.fetchall()
    return [v['original_order_number'] for v in rows]


def fetch_day_all_erp_oids(payment_day, cursor, oids=[]):
    """
    某天的erp订单
    """
    _where = ''
    if oids:
        _where = " and original_order_number in ('"+"','".join(oids)+"') "
    sql = """
    select original_order_number, platform, online_status, shop_id, sum(actual_payment_amount) as pay_amount
    from bi.yy_erp_qianyiapi_history 
    where payment_time_update = %(payment_day)s
    {}
    and order_created_time >= %(created_start)s
    group by original_order_number
    """.format(_where)
    cursor.execute(sql, {
        'payment_day': str(payment_day),
        'created_start': str(payment_day - timedelta(days=1)) + ' 00:00:00'
    })
    rows = cursor.fetchall()
    return {v['original_order_number']: v for v in rows}


def fetch_day_erp_orders(payment_day, cursor, oids=[]):
    """
    某天erp订单
    """
    _where = ''
    if oids:
        _where = " and original_order_number in ('"+"','".join(oids)+"') "
    sql = """
    select erp_id, original_order_number, product_code as sku, system_tracking_number, brush_or_not, platform, 
    online_product_code, product_units, shop_id, actual_payment_amount as pay_amount, shipping_fee, 
    online_status, currency,  product_units
    from bi.yy_erp_qianyiapi_history 
    where payment_time_update = %(payment_day)s
    and order_created_time >= %(created_start)s
    # and order_status != 'CLOSED'
    # and platform = 'TikTok'
    {}
    """.format(_where)
    cursor.execute(sql, {'payment_day': str(payment_day), 'created_start': str(payment_day - timedelta(days=1)) + ' 00:00:00'})
    rows = cursor.fetchall()
    all_skus = []  # 按天分订单，因为成本需要拿支付日期前2个月的成本
    erp_orders = {}  # erp订单
    order_shop_id = {}
    order_sku_quantity = {}  # erp订单的sku数量
    for o in rows:
        if not o['sku']: continue
        all_skus.append(o['sku'])
        if o['original_order_number'] not in erp_orders:
            erp_orders[o['original_order_number']] = {}
        _key = '%s|%s|%s' % (o['sku'], o['online_product_code'], o['product_units'])
        erp_orders[o['original_order_number']].setdefault(_key, []).append(o)
        if o['original_order_number'] not in order_shop_id:
            order_shop_id[o['original_order_number']] = {
                'shop_id': o['shop_id'],
                'amount': o['pay_amount'],
                'online_status': o['online_status']
            }
        else:
            if o['pay_amount']:
                order_shop_id[o['original_order_number']]['amount'] += o['pay_amount']

        # 算千易匹配不上的订单使用
        order_sku_quantity.setdefault(o['original_order_number'], []).append({
            'sku': o['sku'],
            'sku_quantity': o['product_units'],
            'currency': o['currency'],
            'pay_amount': o['pay_amount'],
            'shipping_fee': o['shipping_fee']
        })
    return erp_orders, all_skus, order_shop_id, order_sku_quantity


def fetch_order_detail(all_oids, cursor):
    """
    拿订单detail sku的钱
    """

    sql = """
    select order_sn, platform, mapping_code, sku_id, spu_id, currency, 
    item_paid, voucher_from_platform as platform_subsidy, voucher_from_seller as seller_voucher, 
    original_price, discount_from_platform, shipping_fee as platform_shipping_fee, 
    shipping_fee_discount_from_platform as platform_shipping_fee_discount, order_item_status
    from bi.data_platform_order_detail 
    where order_sn in %(oids)s 
    """
    cursor.execute(sql, {'oids': all_oids})
    rows = cursor.fetchall()
    platform_order_fees = {}
    platform_orders = []
    platform_order_fee_total = {}  # 汇总到订单级别
    for v in rows:
        platform_orders.append(v['order_sn'])
        if v['order_item_status'] == 'canceled': continue

        seller_voucher = Decimal(0)  # lazada应该没有商家优惠，商家优惠已经包含在paid_price里了
        if v['platform'] == 'Shopee':
            seller_voucher = v['seller_voucher']

        # 商品划线后的价格,⚠️()里面是api接口原字段:
            # Lazada = original_price(item_price),
            # Shopee = item_paid(discounted_price),
            # TikTok = original_price(original_price)-voucher_from_seller(seller_discount)
        original_price = v['original_price']
        if v['platform'] == 'Shopee':
            original_price = v['item_paid']
        elif v['platform'] in ['TikTok', 'Tokopedia']:
            tt_seller_voucher = v['seller_voucher'] if v['seller_voucher'] else 0
            original_price = original_price - tt_seller_voucher

        # 商品实付⚠️()里面是api接口原字段：
            # Lazada = item_paid(paid_price)
            # Shopee = item_paid(discounted_price) - voucher_from_seller(discount_from_voucher_seller) - voucher_from_platform(discount_from_voucher_shopee),
            # TikTok = item_paid(sale_price)
        item_paid = v['item_paid']
        if v['platform'] == 'Shopee':
            platform_subsidy = v['platform_subsidy'] if v['platform_subsidy'] else 0
            item_paid = original_price - seller_voucher - platform_subsidy

        if v['platform'] == 'Lazada':
            platform_subsidy = v['platform_subsidy'] if v['platform_subsidy'] else 0
            discount_from_platform = v['discount_from_platform'] if v['discount_from_platform'] else 0
        else:
            platform_subsidy = v['discount_from_platform'] if v['discount_from_platform'] else 0
            discount_from_platform = v['discount_from_platform'] if v['discount_from_platform'] else 0
            if v['platform'] == 'Shopee':
                # 平台卖家补贴 = shopee_discount + voucher_from_shopee
                voucher_from_platform = v['platform_subsidy'] if v['platform_subsidy'] else 0
                platform_subsidy = platform_subsidy + voucher_from_platform
        # if discount_from_platform>0:
        #     print(1111)
        platform_shipping_fee = v['platform_shipping_fee'] if v['platform_shipping_fee'] else 0
        platform_shipping_fee_discount = v['platform_shipping_fee_discount'] if v['platform_shipping_fee_discount'] else 0

        if v['order_sn'] not in platform_order_fees:
            platform_order_fees[v['order_sn']] = {}
        _key = v['mapping_code']
        if _key not in platform_order_fees[v['order_sn']]:
            v['item_paid'] = item_paid
            v['original_price'] = original_price
            v['seller_voucher'] = seller_voucher
            v['platform_subsidy'] = platform_subsidy
            v['platform_shipping_fee'] = platform_shipping_fee
            v['platform_shipping_fee_discount'] = platform_shipping_fee_discount
            v['discount_from_platform'] = discount_from_platform
            # del v['discount_from_platform']
            platform_order_fees[v['order_sn']][_key] = v
        else:
            platform_order_fees[v['order_sn']][_key]['item_paid'] += item_paid
            platform_order_fees[v['order_sn']][_key]['original_price'] += original_price
            platform_order_fees[v['order_sn']][_key]['platform_subsidy'] += platform_subsidy if platform_subsidy else 0
            platform_order_fees[v['order_sn']][_key]['seller_voucher'] += seller_voucher if seller_voucher else 0
            platform_order_fees[v['order_sn']][_key][
                'platform_shipping_fee'] += platform_shipping_fee if platform_shipping_fee else 0
            platform_order_fees[v['order_sn']][_key][
                'platform_shipping_fee_discount'] += platform_shipping_fee_discount if platform_shipping_fee_discount else 0
            platform_order_fees[v['order_sn']][_key]['discount_from_platform'] += discount_from_platform if discount_from_platform else 0
        # 订单级
        if v['order_sn'] not in platform_order_fee_total:
            platform_order_fee_total[v['order_sn']] = {
                'item_paid': v['item_paid'] if v['item_paid'] else 0,
                'original_price': v['original_price'] if v['original_price'] else 0,
                'platform_subsidy': platform_subsidy if platform_subsidy else 0,
                'seller_voucher': seller_voucher if seller_voucher else 0,
                'platform_shipping_fee': platform_shipping_fee if platform_shipping_fee else 0,
                'platform_shipping_fee_discount': platform_shipping_fee_discount if platform_shipping_fee_discount else 0,
                'discount_from_platform': discount_from_platform if discount_from_platform else 0
            }
        else:
            platform_order_fee_total[v['order_sn']]['item_paid'] += v['item_paid'] if v['item_paid'] else 0
            platform_order_fee_total[v['order_sn']]['original_price'] += v['original_price'] if v['original_price'] else 0
            platform_order_fee_total[v['order_sn']]['platform_subsidy'] += platform_subsidy if platform_subsidy else 0
            platform_order_fee_total[v['order_sn']]['seller_voucher'] += seller_voucher if seller_voucher else 0
            platform_order_fee_total[v['order_sn']]['platform_shipping_fee'] += platform_shipping_fee if platform_shipping_fee else 0
            platform_order_fee_total[v['order_sn']]['platform_shipping_fee_discount'] += platform_shipping_fee_discount if platform_shipping_fee_discount else 0
            platform_order_fee_total[v['order_sn']]['discount_from_platform'] += discount_from_platform if discount_from_platform else 0
    return platform_orders, platform_order_fees, platform_order_fee_total


def fetch_qianyi_db_order_info(all_oids, qianyi_cursor):
    """
    拿千易备库的数据 这里不带日期，因为千易订单支付日期跟平台有差
    """
    if not all_oids:
        return {}
    sql = """
    select id, online_order_id, parent_id from gerp.ge_order 
    where online_order_id in %(oids)s 
    and is_deleted = 0
    # and parent_id is NUll 
    # and date_format(pay_time_local,'%%Y-%%m-%%d')
    """
    qianyi_cursor.execute(sql, {'oids': all_oids})
    rows = qianyi_cursor.fetchall() 
    _t = {}
    for v in rows:
        if v['online_order_id'] not in _t:
            _t[v['online_order_id']] = {}
        _t[v['online_order_id']].setdefault(v['parent_id'], []).append(v['id'])

    qianyi_oids = {}
    for order_id, parent_ids in _t.items():
        for parent_id, _ids in parent_ids.items():
            # 如果有多个则过滤掉拆单前的
            if parent_id is None and len(parent_ids) > 1: continue
            for _id in _ids:
                qianyi_oids[_id] = order_id
    if not qianyi_oids:
        return {}
    sql = """
    select o.order_id, o.online_transaction_id, o.online_item_id, o.sku, o.online_sku_code, o.sku_quantity as quantity, 
    o.currency, o.pay_amount, o.shipping_price 
    from gerp.ge_order_sku as o
    left join gerp.ge_sku as s on s.sku = o.sku
    where o.order_id in %(qian_oids)s and o.is_deleted = 0 and s.type='SINGLE'
    """
    qianyi_cursor.execute(sql, {'qian_oids': list(set(qianyi_oids.keys()))})
    qianyi_order_rows = qianyi_cursor.fetchall()
    qianyi_orders = {}
    for v in qianyi_order_rows:
        order_id = qianyi_oids[v['order_id']]
        online_item_id = v['online_item_id']
        if v['online_item_id'] and v['online_item_id'].find('-') == -1:
            if v['online_transaction_id'] != order_id:  # 说明是TT, 需要特殊处理
                online_item_id = '%s-%s' % (v['online_transaction_id'], v['online_item_id'])
        _key = online_item_id
        if order_id not in qianyi_orders:
            qianyi_orders[order_id] = {}
        if _key not in qianyi_orders[order_id]:
            qianyi_orders[order_id][_key] = []
        qianyi_orders[order_id][_key].append(v)
    return qianyi_orders


def build_not_platform_order_fee(oid, erp_order_dict, sku_day_purchase_info, day_exchange_rate, qy_order_dict):
    """
    非平台订单
    """

    data = []
    for sku_spu_key, sku_arr in erp_order_dict.items():
        for sku_item in sku_arr:
            purchase_info = sku_day_purchase_info.get(sku_item['sku'], {})
            purchase_price = Decimal(0)
            if purchase_info and purchase_info['purchase_cost']:
                purchase_price = Decimal(purchase_info['purchase_cost']) * Decimal(sku_item['quantity'])

            shipping_fee = Decimal(sku_item['shipping_fee']) if sku_item['shipping_fee'] else 0
            paid_price = sku_item['pay_amount'] - shipping_fee
            _exchange_rate = day_exchange_rate.get(sku_item['currency'], 0)
            item = {
                'erp_id': sku_item['erp_id'],
                'order_sn': oid,
                'sku': sku_item['sku'],
                'marked_price': 0,
                'platform_subsidy': 0,
                'paid_price': paid_price,
                'seller_voucher': 0,
                'platform_shipping_fee': 0,
                'platform_shipping_fee_discount': 0,
                'discount_from_platform': 0,
                'product_cost_cny': purchase_price,
                'platform_subsidy_usd': 0,
                'discount_from_platform_usd':0,
                'paid_price_usd': paid_price / _exchange_rate if _exchange_rate else 0,
                'seller_voucher_usd': 0,
                'product_cost_usd': purchase_price / day_exchange_rate.get('CNY', 0) if day_exchange_rate.get('CNY', 0) else 0,
                'platform_shipping_fee': 0,
                'platform_shipping_fee_discount': 0,
            }
            data.append(item)
    return data


def build_platform_order_fee(oid, erp_order_dict, sku_day_purchase_info, day_exchange_rate, qy_order_dict,
                             platform_order_fees):
    """
    处理平台订单，把平台订单的钱分给erp订单sku
    """
    data = []
    for sku_spu_key, sku_arr in erp_order_dict.items():
        # 是平台订单，但是从千易发了赠品，需要算成本，不算收入
        if sku_spu_key not in platform_order_fees:
            platform_order_fees[sku_spu_key] = {
                'item_paid': 0,
                'platform_subsidy': 0,
                'seller_voucher': 0,
                'platform_shipping_fee': 0,
                'platform_shipping_fee_discount': 0,
                'original_price': 0,
                'discount_from_platform':0,
                'currency': sku_arr[0]['currency']
            }

        detail_order_fee_dict = platform_order_fees[sku_spu_key]
        # 组合品需要分摊，按照采购成本分摊
        total_purchase_price = Decimal(0)
        for sku_item in sku_arr:
            try:
                sku = sku_item['sku']
                sku_quantity = sku_item['quantity'] if sku_item['quantity'] else 0
                purchase_info = sku_day_purchase_info.get(sku, {})
                if purchase_info and purchase_info['purchase_cost']:
                    purchase_price = Decimal(purchase_info['purchase_cost']) * Decimal(sku_quantity)
                else:
                    purchase_price = 0
                    # logger.warning('sku: %s 没有采购成本, %s' % (sku, oid))
                total_purchase_price += purchase_price
            except Exception as e:
                purchase_info = sku_day_purchase_info.get(sku_item['sku'], {})
                print(7777, oid, sku_item, purchase_info, e)
                continue

        for sku_item in sku_arr:
            sku = sku_item['sku']
            sku_quantity = sku_item['quantity']
            try:
                purchase_info = sku_day_purchase_info.get(sku, {})
                purchase_price = Decimal(0)
                if purchase_info and purchase_info['purchase_cost']:
                    purchase_price = Decimal(purchase_info['purchase_cost']) * Decimal(sku_quantity)

                _rate = purchase_price / total_purchase_price if total_purchase_price else 0
                if len(sku_arr) == 1:  # 如果只有一个sku,则不用分摊
                    _rate = Decimal(1)
                # print(sku_item, total_purchase_price, purchase_price, _rate, fee_info['item_paid'] / Decimal(10000) * _rate)
                original_price = detail_order_fee_dict['original_price'] / Decimal(10000) * _rate
                platform_subsidy = detail_order_fee_dict['platform_subsidy'] / Decimal(10000) * _rate
                paid_price = detail_order_fee_dict['item_paid'] / Decimal(10000) * _rate
                seller_voucher = detail_order_fee_dict['seller_voucher'] / Decimal(10000) * _rate
                platform_shipping_fee = detail_order_fee_dict['platform_shipping_fee'] / Decimal(10000) * _rate
                platform_shipping_fee_discount = detail_order_fee_dict['platform_shipping_fee_discount'] / Decimal(10000) * _rate
                discount_from_platform = detail_order_fee_dict['discount_from_platform'] / Decimal(10000) * _rate
                _exchange_rate = day_exchange_rate.get(detail_order_fee_dict['currency'], 0)

                item = {
                    'erp_id': sku_item['erp_id'],
                    'order_sn': oid,
                    'sku': sku,
                    'marked_price': original_price,
                    'platform_subsidy': platform_subsidy,
                    'paid_price': paid_price,
                    'seller_voucher': seller_voucher,
                    'platform_shipping_fee': platform_shipping_fee,
                    'platform_shipping_fee_discount': platform_shipping_fee_discount,
                    'product_cost_cny': purchase_price,
                    'platform_subsidy_usd': platform_subsidy / _exchange_rate if _exchange_rate else 0,
                    'paid_price_usd': paid_price / _exchange_rate if _exchange_rate else 0,
                    'seller_voucher_usd': seller_voucher / _exchange_rate if _exchange_rate else 0,
                    'product_cost_usd': purchase_price / day_exchange_rate.get('CNY', 0) if day_exchange_rate.get('CNY', 0) else 0,
                    'platform_shipping_fee': platform_shipping_fee,
                    'platform_shipping_fee_discount': platform_shipping_fee_discount,
                    'discount_from_platform': discount_from_platform,
                    'discount_from_platform_usd': discount_from_platform / _exchange_rate if _exchange_rate else 0,
                }
                data.append(item)
            except Exception as e:
                print(333332222, e, oid)
                continue
    return data