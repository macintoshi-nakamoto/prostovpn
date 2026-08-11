/* SPDX-License-Identifier: MIT
 *
 * Право запускать службу туннеля без прав администратора.
 */

package main

import (
	"fmt"

	"golang.org/x/sys/windows"
)

/*
Кто и что может делать со службой туннеля.

  SY — SYSTEM, полный набор для самой службы
  BA — администраторы, включая удаление
  IU — тот, кто сидит за этой машиной: запуск, остановка, опрос

Пускать сюда всех подряд (AU, authenticated users) нельзя: службу можно
запускать по сети и от имени служебных учёток. IU выдаётся только на
время интерактивного входа — ровно тому, кто нажал кнопку.

Скрипты (PreUp/PostUp) движок не поддерживает вовсе, иначе право запуска
означало бы выполнение команд от имени SYSTEM: конфиг лежит в профиле
пользователя и правится им же.
*/
const tunnelServiceSDDL = "D:" +
	"(A;;CCLCSWRPWPDTLOCRRC;;;SY)" +
	"(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)" +
	"(A;;CCLCSWLORPWPRC;;;IU)"

/*
Выдаёт интерактивному пользователю право запускать и останавливать службу.

Вызывается один раз — при установке, из процесса с правами администратора.
*/
func allowInteractiveUserToStart(handle windows.Handle) error {
	sd, err := windows.SecurityDescriptorFromString(tunnelServiceSDDL)
	if err != nil {
		return fmt.Errorf("разбор прав службы: %w", err)
	}
	dacl, _, err := sd.DACL()
	if err != nil {
		return fmt.Errorf("список прав службы: %w", err)
	}
	err = windows.SetSecurityInfo(
		handle,
		windows.SE_SERVICE,
		windows.DACL_SECURITY_INFORMATION,
		nil, nil, dacl, nil,
	)
	if err != nil {
		return fmt.Errorf("назначение прав службы: %w", err)
	}
	return nil
}
