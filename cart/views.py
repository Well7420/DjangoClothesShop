from django.shortcuts import get_object_or_404, redirect
from django.views.generic import View
from django.http import JsonResponse, HttpResponse
from django.template.response import TemplateResponse
from django.contrib import messages
from django.db import transaction
from main.models import Product, ProductSize
from .models import Cart, CartItem
from .forms import AddToCartForm
import json
from django.middleware.csrf import get_token


class CartMixin:
    def get_cart(self, request):
        if hasattr(request, 'cart'):
            return request.cart

        if not request.session.session_key:
            request.session.create()

        cart, created = Cart.objects.get_or_create(
            session_key=request.session.session_key
        )

        request.session['cart_id'] = cart.id
        request.session.modified = True
        return cart


class CartModalView(CartMixin, View):
    def get(self, request):
        cart = self.get_cart(request)
        context = {
            'cart': cart,
            'cart_items': cart.items.select_related(
                'product',
                'product_size__size'
            ).order_by('-added_at')
        }
        return TemplateResponse(request, 'cart/cart_modal.html', context)


class AddToCartView(CartMixin, View):
    @transaction.atomic
    def post(self, request, slug):
        cart = self.get_cart(request)
        product = get_object_or_404(Product, slug=slug)

        form = AddToCartForm(request.POST, product=product)

        if not form.is_valid():  # проверка на валидность формы
            return JsonResponse({
                'error': 'Invalid form data',
                'errors': form.errors,
            }, status=400)

        size_id = form.cleaned_data.get('size_id')  # проверка размера
        if size_id:
            product_size = get_object_or_404(
                ProductSize,
                id=size_id,
                product=product
            )
        else:
            product_size = product.product_sizes.filter(stock__gt=0).first()
            if not product_size:
                return JsonResponse({
                    'error': 'No sizes available'
                }, status=400)

        quantity = form.cleaned_data['quantity']  # проверка количества товара
        if product_size.stock < quantity:
            return JsonResponse({
                'error': f'Only {product_size.stock} items available'
            }, status=400)

        existing_item = cart.items.filter(  # проверка на существующий товар в корзине
            product=product,
            product_size=product_size,
        ).first()

        if existing_item:  # сумма кол-ва товаров, что уже в корзине и что добавляем
            total_quantity = existing_item.quantity + quantity
            if total_quantity > product_size.stock:
                return JsonResponse({
                    'error': f"Cannot add {quantity} items. Only {product_size.stock - existing_item.quantity} more available."
                }, status=400)

        cart_item = cart.add_product(product, product_size, quantity)

        request.session['cart_id'] = cart.id
        request.session.modified = True
        new_csrf_token = get_token(request)

        if request.headers.get('HX-Request'):
            # не переход, а открытие корзины
            return redirect('cart:cart_modal')
        else:
            return JsonResponse({
                'success': True,
                'total_items': cart.total_items,
                'message': f"{product.name} added to cart",
                'cart_item_id': cart_item.id,
                'new_csrf_token': new_csrf_token
            })


class UpdateCartItemView(CartMixin, View):
    @transaction.atomic
    def post(self, request, item_id):
        cart = self.get_cart(request)
        cart_item = get_object_or_404(CartItem, id=item_id, cart=cart)

        quantity = int(request.POST.get('quantity', 1))

        if quantity < 0:
            return JsonResponse({'error': 'Invalid quantity'}, status=400)

        if quantity == 0:
            cart_item.delete()
        else:
            if quantity > cart_item.product_size.stock:
                return JsonResponse({
                    'error': f'Only {cart_item.product_size.stock} items available'
                }, status=400)

            cart_item.quantity = quantity
            cart_item.save()

        request.session['cart_id'] = cart.id
        request.session.modified = True

        context = {
            'cart': cart,
            'cart_items': cart.items.select_related(
                'product',
                'product_size__size',
            ).order_by('-added_at')
        }
        # обновление корзины после удаления товара
        return TemplateResponse(request, 'cart/cart_modal.html', context)


class RemoveCartItemView(CartMixin, View):
    def post(self, request, item_id):
        cart = self.get_cart(request)

        try:
            cart_item = cart.items.get(id=item_id)
            cart_item.delete()

            request.session['cart_id'] = cart.id
            request.session.modified = True

            context = {
                'cart': cart,
                'cart_items': cart.items.select_related(
                    'product',
                    'product_size__size',
                ).order_by('-added_at')
            }
            return TemplateResponse(request, 'cart/cart_modal.html', context)
        except CartItem.DoesNotExist:
            return JsonResponse({'error': 'Item not found'}, status=400)


class CartCountView(CartMixin, View):  # кол-во товаров в корзине
    def get(self, request):
        cart = self.get_cart(request)
        return JsonResponse({
            'total_items': cart.total_items,
            'subtotal': float(cart.subtotal)  # метод прописан в models
        })


class ClearCartView(CartMixin, View):  # очистка корзины
    def post(self, request):
        cart = self.get_cart(request)
        cart.clear()  # метод прописан в models

        request.session['cart_id'] = cart.id
        request.session.modified = True

        if request.headers.get('HX-Request'):
            return TemplateResponse(request, 'cart/cart_empty.html', {
                'cart': cart
            })
        return JsonResponse({
            'succes': True,
            'message': 'Cart cleared'
        })


class CartSummaryView(CartMixin, View):  # вывод товаров, которые находятся в корзине
    def get(self, request):
        cart = self.get_cart(request)
        context = {
            'cart': cart,
            'cart_items': cart.items.select_related(
                'product',
                'product_size__size'
            ).order_by('-added_at')
        }
        return TemplateResponse(request, 'cart/cart_summary.html', context)
